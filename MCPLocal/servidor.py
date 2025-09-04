from __future__ import annotations
import json, os, random, string, time, socket
from dataclasses import asdict, dataclass
from typing import List, Dict, Any, Optional, Tuple

from mcp.server.fastmcp import FastMCP
from mcp.server.session import ServerSession

import dns.resolver
import dns.name
import dns.message
import dns.query
import dns.rdatatype
import dns.dnssec
import dns.exception


LOG_PATH = os.environ.get("DNS_MCP_LOG", "dns_mcp.log.jsonl")

def log_event(event: Dict[str, Any]) -> None:
    try:
        event["ts"] = time.time()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass

def to_str_list(rrset) -> List[str]:
    try:
        return [r.to_text() for r in rrset]
    except Exception:
        return []

def random_label(n: int = 10) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def make_resolver(servers: Optional[List[str]] = None, timeout: float = 3.0) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.lifetime = timeout
    r.timeout = timeout
    if servers:
        r.nameservers = servers
    return r

def resolve_rr(resolver: dns.resolver.Resolver, name: str, rtype: str):
    try:
        ans = resolver.resolve(name, rtype, raise_on_no_answer=False)
        return ans.rrset, None
    except dns.resolver.NXDOMAIN:
        return None, "NXDOMAIN"
    except dns.resolver.NoAnswer:
        return None, "NO_ANSWER"
    except dns.exception.DNSException as e:
        return None, f"DNS_ERROR:{type(e).__name__}"

def get_authoritative_ns_ips(domain: str) -> List[str]:

    res = make_resolver()
    ns_rr, err = resolve_rr(res, domain, "NS")
    if not ns_rr:
        return []
    ips: List[str] = []
    for ns in ns_rr:
        host = str(ns.target).rstrip(".")
        for typ in ("A", "AAAA"):
            rr, _ = resolve_rr(res, host, typ)
            if rr:
                for r in rr:
                    ip = r.address if hasattr(r, "address") else str(r)
                    ips.append(ip)
    return list(dict.fromkeys(ips))  # únicos, preservando orden

def query_authoritative(name: str, rtype: str, ns_ip: str):

    q = dns.message.make_query(name, rtype, want_dnssec=True)
    q.flags &= ~dns.flags.RD  # sin recursión
    try:
        resp = dns.query.udp(q, ns_ip, timeout=3.0)
        # preferimos Answer; si viene vacío, ver Authority
        if resp.answer:
            return resp.answer[0]
        # a veces el autoritativo delega y solo da NS en authority
        return None
    except Exception:
        return None

def flatten_rr_text(rrset) -> List[str]:
    if not rrset:
        return []
    return [r.to_text() for r in rrset]


@dataclass
class Hallazgo:
    tipo: str
    severidad: str  
    detalle: str

@dataclass
class ResultadoSaludDNS:
    dominio: str
    recursivo: Dict[str, Any]
    autoritativo: Dict[str, Any]
    hallazgos: List[Hallazgo]

@dataclass
class ResultadoCorreo:
    dominio: str
    mx: List[str]
    spf: Optional[str]
    dmarc: Optional[str]
    hallazgos: List[Hallazgo]

@dataclass
class ResultadoDNSSEC:
    dominio: str
    tiene_ds_en_padre: bool
    dnskey_algoritmos: List[int]
    soa_firmada_valida: Optional[bool]
    detalles: List[str]
    hallazgos: List[Hallazgo]

@dataclass
class ResultadoPropagacion:
    dominio: str
    resolutores: List[str]
    respuestas: Dict[str, Dict[str, Any]]  
    diferencias: Dict[str, Any]


mcp = FastMCP("MCP-DNS")

@mcp.tool()
def ping() -> str:
    return "pong"


@mcp.tool()
def salud_dns(dominio: str) -> Dict[str, Any]:

    start = time.time()
    hall: List[Hallazgo] = []

    rec = make_resolver()
    a_rr, _ = resolve_rr(rec, dominio, "A")
    aaaa_rr, _ = resolve_rr(rec, dominio, "AAAA")
    ns_rr, err_ns = resolve_rr(rec, dominio, "NS")
    soa_rr, err_soa = resolve_rr(rec, dominio, "SOA")
    cname_rr, _ = resolve_rr(rec, dominio, "CNAME")  #

    # Autoritativo
    auth_ips = get_authoritative_ns_ips(dominio)
    auth = {"A": [], "AAAA": [], "NS": [], "SOA": []}
    for typ in ("A", "AAAA", "NS", "SOA"):
        vistas = []
        for ip in auth_ips[:4]:  # limitamos a 4 NS
            rr = query_authoritative(dominio, typ, ip)
            if rr:
                vistas.extend(flatten_rr_text(rr))
        auth[typ] = sorted(list(set(vistas)))

    # Wildcard (comodín): probar subdominio aleatorio
    test_sub = f"{random_label()}.{dominio}".rstrip(".")
    rand_a, rand_err = resolve_rr(rec, test_sub, "A")
    if rand_a and len(rand_a) > 0:
        hall.append(Hallazgo("wildcard", "warning",
                             f"Resuelve {test_sub} → {to_str_list(rand_a)} (posible comodín)"))

    # TTLs desbalanceados (heurística simple en apex)
    ttl_vals = []
    for rr in (a_rr, aaaa_rr, ns_rr, soa_rr):
        if rr:
            ttl_vals.append(rr.ttl)
    if ttl_vals:
        tmin, tmax = min(ttl_vals), max(ttl_vals)
        if tmax >= 4 * max(1, tmin):
            hall.append(Hallazgo("ttls_desbalanceados", "info",
                                 f"TTLs variados en apex (min={tmin}, max={tmax})"))

    # CNAME colgante 
    if cname_rr:
        try:
            target = str(cname_rr[0].target).rstrip(".")
            a_tgt, _ = resolve_rr(rec, target, "A")
            aaaa_tgt, _ = resolve_rr(rec, target, "AAAA")
            if not a_tgt and not aaaa_tgt:
                hall.append(Hallazgo("cname_colgante", "error",
                                     f"CNAME apunta a {target} que no resuelve A/AAAA"))
        except Exception:
            pass

    resultado = ResultadoSaludDNS(
        dominio=dominio,
        recursivo={
            "A": to_str_list(a_rr),
            "AAAA": to_str_list(aaaa_rr),
            "NS": [str(r.target).rstrip(".") for r in (ns_rr or [])],
            "SOA": to_str_list(soa_rr),
        },
        autoritativo=auth,
        hallazgos=hall,
    )
    out = asdict(resultado)
    log_event({"tool": "salud_dns", "dominio": dominio, "dur_ms": int(1000*(time.time()-start)), "out_size": len(json.dumps(out))})
    return out

