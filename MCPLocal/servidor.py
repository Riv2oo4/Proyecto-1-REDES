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

# correo_politicas(dominio) 

@mcp.tool()
def correo_politicas(dominio: str) -> Dict[str, Any]:

    start = time.time()
    res = make_resolver()
    hall: List[Hallazgo] = []

    mx_rr, _ = resolve_rr(res, dominio, "MX")
    txt_rr, _ = resolve_rr(res, dominio, "TXT")
    dmarc_rr, _ = resolve_rr(res, f"_dmarc.{dominio}", "TXT")

    mx_list = []
    if mx_rr:
        try:
            mx_list = sorted([r.to_text() for r in mx_rr], key=lambda s: int(s.split()[0]))
        except Exception:
            mx_list = [r.to_text() for r in mx_rr]
    else:
        hall.append(Hallazgo("sin_mx", "warning", "El dominio no publica registros MX."))

    spf_txt = None
    if txt_rr:
        for r in txt_rr:
            txt = r.to_text().strip('"')
            if txt.lower().startswith("v=spf1"):
                spf_txt = txt
                break
    if not spf_txt:
        hall.append(Hallazgo("sin_spf", "warning", "No se encontró SPF en TXT del apex."))

    dmarc_txt = None
    if dmarc_rr:
        for r in dmarc_rr:
            txt = r.to_text().strip('"')
            if txt.lower().startswith("v=dmarc1"):
                dmarc_txt = txt
                break
    if not dmarc_txt:
        hall.append(Hallazgo("sin_dmarc", "warning", "No se encontró política DMARC en _dmarc."))

    resultado = ResultadoCorreo(
        dominio=dominio,
        mx=mx_list,
        spf=spf_txt,
        dmarc=dmarc_txt,
        hallazgos=hall,
    )
    out = asdict(resultado)
    log_event({"tool": "correo_politicas", "dominio": dominio, "dur_ms": int(1000*(time.time()-start)), "out_size": len(json.dumps(out))})
    return out

# estado_dnssec(dominio) 

def parent_zone(name: dns.name.Name) -> dns.name.Name:
    return dns.name.Name(name.labels[1:])

@mcp.tool()
def estado_dnssec(dominio: str) -> Dict[str, Any]:

    start = time.time()
    res = make_resolver()
    detalles: List[str] = []
    hall: List[Hallazgo] = []

    name = dns.name.from_text(dominio)
    # 1) DS en el padre
    tiene_ds = False
    try:
        ds_rr, _ = resolve_rr(res, dominio, "DS")
        if ds_rr and len(ds_rr) > 0:
            tiene_ds = True
            detalles.append(f"DS en el padre: {len(ds_rr)} registro(s).")
        else:
            detalles.append("No hay DS publicado en el padre.")
    except Exception as e:
        detalles.append(f"Error consultando DS: {e}")

    # 2) DNSKEY en el apex
    dnskey_rr, _ = resolve_rr(res, dominio, "DNSKEY")
    algos = []
    if dnskey_rr:
        for r in dnskey_rr:
            try:
                algos.append(r.algorithm)
            except Exception:
                pass
        detalles.append(f"DNSKEY presente: {len(dnskey_rr)} clave(s), algoritmos={sorted(list(set(algos)))}")
    else:
        hall.append(Hallazgo("sin_dnskey", "error", "No se pudo obtener DNSKEY del dominio."))

    # Verificación práctica DS <-> DNSKEY (coincidencia de huellas)
    if tiene_ds and dnskey_rr:
        try:
            matches = 0
            for key in dnskey_rr:
                for ds in ds_rr:
                    calc = dns.dnssec.make_ds(name, key, ds.digest_type)
                    if calc == ds:
                        matches += 1
            if matches == 0:
                hall.append(Hallazgo("ds_dnskey_mismatch", "error",
                                     "Ningún DNSKEY coincide con DS del padre (posible ruptura de cadena)."))
        except Exception as e:
            detalles.append(f"Error comparando DS/DNSKEY: {e}")

    # Validar firma de SOA con DNSKEY (si hay RRSIG)
    soa_signed_ok: Optional[bool] = None
    try:
        # obtener RRsets con firmas (want_dnssec)
        q = dns.message.make_query(dominio, "SOA", want_dnssec=True)
        ans = dns.query.udp(q, make_resolver().nameservers[0], timeout=3.0)
        rrset_soa = None
        rrsig_soa = None
        for rrset in ans.answer:
            if rrset.rdtype == dns.rdatatype.SOA:
                rrset_soa = rrset
            if rrset.rdtype == dns.rdatatype.RRSIG and rrset.covers() == dns.rdatatype.SOA:
                rrsig_soa = rrset
        if rrset_soa and rrsig_soa and dnskey_rr:
            # construir keyring
            keyring = {}
            for k in dnskey_rr:
                name_text = dominio.rstrip(".")
                keyring[(dns.name.from_text(name_text), k.key_tag(), k.algorithm)] = k
            dns.dnssec.validate(rrset_soa, rrsig_soa, keyring)
            soa_signed_ok = True
            detalles.append("SOA validado contra RRSIG y DNSKEY (OK).")
        else:
            detalles.append("No se pudo validar SOA (faltan RRSIG/DNSKEY en respuesta autoritativa).")
    except Exception as e:
        soa_signed_ok = False
        hall.append(Hallazgo("firma_soa_invalida", "warning", f"No se validó SOA: {e}"))

    resultado = ResultadoDNSSEC(
        dominio=dominio,
        tiene_ds_en_padre=tiene_ds,
        dnskey_algoritmos=sorted(list(set(algos))),
        soa_firmada_valida=soa_signed_ok,
        detalles=detalles,
        hallazgos=hall,
    )
    out = asdict(resultado)
    log_event({"tool": "estado_dnssec", "dominio": dominio, "dur_ms": int(1000*(time.time()-start)), "out_size": len(json.dumps(out))})
    return out

# propagacion(dominio, resolutores=[...]) 

@mcp.tool()
def propagacion(dominio: str, resolutores: Optional[List[str]] = None) -> Dict[str, Any]:

    start = time.time()
    if not resolutores:
        resolutores = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]

    respuestas: Dict[str, Dict[str, Any]] = {}
    for ip in resolutores:
        r = make_resolver([ip])
        a_rr, _ = resolve_rr(r, dominio, "A")
        aaaa_rr, _ = resolve_rr(r, dominio, "AAAA")
        ns_rr, _ = resolve_rr(r, dominio, "NS")
        txt_rr, _ = resolve_rr(r, dominio, "TXT")
        txt_sample = [t.to_text().strip('"') for t in (txt_rr or [])][:3]
        respuestas[ip] = {
            "A": to_str_list(a_rr),
            "AAAA": to_str_list(aaaa_rr),
            "NS": [str(n.target).rstrip(".") for n in (ns_rr or [])],
            "TXT_sample": txt_sample,
        }

    # Diferencias simples por tipo
    diffs: Dict[str, Any] = {}
    for typ in ("A", "AAAA", "NS"):
        sets = {ip: set(respuestas[ip][typ]) for ip in respuestas}
        universe = set().union(*sets.values()) if sets else set()
        per_ip = {ip: sorted(list(universe - sets[ip])) for ip in respuestas}
        # ip -> qué le "falta" respecto al conjunto unión
        diffs[typ] = per_ip

    resultado = ResultadoPropagacion(
        dominio=dominio,
        resolutores=resolutores,
        respuestas=respuestas,
        diferencias=diffs,
    )
    out = asdict(resultado)
    log_event({"tool": "propagacion", "dominio": dominio, "dur_ms": int(1000*(time.time()-start)), "out_size": len(json.dumps(out))})
    return out
