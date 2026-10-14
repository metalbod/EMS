"""Microsoft Entra ID sign-in (OpenID Connect, authorization-code flow with PKCE) — protocol helpers.

Kept free of FastAPI/DB so each step is unit-testable; routers/sso.py wires them to the endpoints. Network calls
(`exchange_code`, `signing_key`) are module-level functions so tests can replace them.
"""
import base64
import hashlib
import re
import secrets
from typing import Any, Dict, List
from urllib.parse import urlencode

import jwt
import requests

AUTH_BASE = "https://login.microsoftonline.com"
PENDING_TTL_SECONDS = 600       # a redirect to Microsoft must come back within 10 minutes
CODE_TTL_SECONDS = 60           # the one-time code EMS hands the browser afterwards
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class SsoError(Exception):
    """A sign-in failed in a way that should send the person back to the login screen with a short code."""
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def is_guid(value: str) -> bool:
    return bool(value and _GUID.match(value.strip()))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pkce_pair():
    """(verifier, S256 challenge)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def issuer(tenant_id: str) -> str:
    return f"{AUTH_BASE}/{tenant_id}/v2.0"


def build_authorize_url(tenant_id: str, client_id: str, redirect_uri: str, state: str, nonce: str, challenge: str) -> str:
    return f"{AUTH_BASE}/{tenant_id}/oauth2/v2.0/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query",
        "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def exchange_code(tenant_id: str, client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str) -> Dict[str, Any]:
    """Swap the authorization code for tokens at Microsoft's token endpoint (server to server)."""
    try:
        res = requests.post(f"{AUTH_BASE}/{tenant_id}/oauth2/v2.0/token", data={
            "client_id": client_id, "client_secret": client_secret, "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "code_verifier": verifier, "scope": "openid profile email",
        }, timeout=15)
    except requests.RequestException:
        raise SsoError("failed", "Could not reach Microsoft")
    if res.status_code != 200:
        try:
            err = res.json()
            detail = f"{err.get('error', 'error')}: {(err.get('error_description') or '')[:200]}"
        except ValueError:
            detail = f"HTTP {res.status_code}"
        raise SsoError("failed", f"Microsoft refused the sign-in ({detail})")
    return res.json()


_jwk_clients: Dict[str, "jwt.PyJWKClient"] = {}


def signing_key(tenant_id: str, id_token: str):
    """The public key that signed `id_token`, from the tenant's published keys (cached; fetched again when Microsoft
    rotates them)."""
    client = _jwk_clients.get(tenant_id)
    if client is None:
        client = _jwk_clients[tenant_id] = jwt.PyJWKClient(f"{AUTH_BASE}/{tenant_id}/discovery/v2.0/keys", cache_keys=True, lifespan=3600)
    try:
        return client.get_signing_key_from_jwt(id_token).key
    except (jwt.PyJWKClientError, jwt.DecodeError):
        raise SsoError("failed", "Could not verify Microsoft's signing key")


def validate_id_token(id_token: str, tenant_id: str, client_id: str, nonce: str) -> Dict[str, Any]:
    """Verify the ID token's signature (RS256 only), issuer, audience, expiry and nonce, and that it came from the
    company's own tenant. Returns the claims; raises SsoError otherwise."""
    key = signing_key(tenant_id, id_token)
    try:
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"], audience=client_id, issuer=issuer(tenant_id),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=120,
        )
    except jwt.InvalidTokenError as e:
        raise SsoError("failed", f"The sign-in token was not valid ({e.__class__.__name__})")
    if claims.get("tid") != tenant_id:
        raise SsoError("failed", "The sign-in came from a different Microsoft tenant")
    if not claims.get("nonce") or not secrets.compare_digest(str(claims["nonce"]), nonce):
        raise SsoError("failed", "The sign-in did not match this request")
    if not claims.get("oid"):
        raise SsoError("failed", "Microsoft did not return a user id")
    return claims


def candidate_emails(claims: Dict[str, Any]) -> List[str]:
    """The addresses a Microsoft account may be known by in EMS (lower-cased, de-duplicated)."""
    out = []
    for k in ("email", "preferred_username", "upn"):
        v = str(claims.get(k) or "").strip().lower()
        if "@" in v and v not in out:
            out.append(v)
    return out
