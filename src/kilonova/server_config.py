"""quasar ServerConfig.xml support (the UASDK-style backend config C++ servers ship).

Honoured: endpoint URL (``[NodeName]`` resolves to all interfaces), security
policy/message-security-mode pairs (None, Basic256Sha256 Sign / SignAndEncrypt),
server certificate/private key paths, and anonymous/user-password identity
token toggles. Everything else (PKI trust lists, session/subscription limits,
tracing) is logged as unsupported rather than silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from asyncua import ua
from lxml import etree

_log = logging.getLogger(__name__)

_POLICY_MAP = {
    ("http://opcfoundation.org/UA/SecurityPolicy#None", "None"):
        ua.SecurityPolicyType.NoSecurity,
    ("http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256", "Sign"):
        ua.SecurityPolicyType.Basic256Sha256_Sign,
    ("http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256", "SignAndEncrypt"):
        ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
}

_UNSUPPORTED = ("MaxSessionCount", "MaxSubscriptionCount", "Trace",
                "CertificateTrustListLocation", "CertificateRevocationListLocation")


@dataclass
class ServerConfig:
    endpoint_url: str | None = None
    security_policies: list = field(default_factory=list)
    certificate_path: str | None = None
    private_key_path: str | None = None
    enable_anonymous: bool = True
    enable_user_pw: bool = False


def _text(root, tag: str) -> str | None:
    element = root.find(f".//{tag}")
    return element.text if element is not None and element.text else None


def load_server_config(path: str | Path) -> ServerConfig:
    tree = etree.parse(str(path))
    root = tree.getroot()
    for element in root.iter():
        tag = etree.QName(element).localname if isinstance(element.tag, str) else ""
        if tag in _UNSUPPORTED and element.text and element.text.strip():
            _log.warning("ServerConfig: %s is not supported by kilonova yet", tag)

    config = ServerConfig()
    url = _text(root, "{*}Url") or _text(root, "Url")
    if url:
        config.endpoint_url = url.replace("[NodeName]", "0.0.0.0")

    for setting in root.iter():
        if not isinstance(setting.tag, str):
            continue
        if etree.QName(setting).localname != "SecuritySetting":
            continue
        policy = _text(setting, "{*}SecurityPolicy") or _text(setting, "SecurityPolicy")
        for mode_el in setting.iter():
            if isinstance(mode_el.tag, str) and \
                    etree.QName(mode_el).localname == "MessageSecurityMode" and mode_el.text:
                mapped = _POLICY_MAP.get((policy, mode_el.text.strip()))
                if mapped is not None:
                    config.security_policies.append(mapped)
                else:
                    _log.warning("ServerConfig: unsupported security setting %s/%s",
                                 policy, mode_el.text.strip())

    base = Path(path).parent
    cert = _text(root, "{*}ServerCertificate") or _text(root, "ServerCertificate")
    key = _text(root, "{*}ServerPrivateKey") or _text(root, "ServerPrivateKey")
    if cert:
        config.certificate_path = str((base / cert).resolve())
    if key:
        config.private_key_path = str((base / key).resolve())

    anonymous = _text(root, "{*}EnableAnonymous") or _text(root, "EnableAnonymous")
    user_pw = _text(root, "{*}EnableUserPw") or _text(root, "EnableUserPw")
    if anonymous is not None:
        config.enable_anonymous = anonymous.strip().lower() == "true"
    if user_pw is not None:
        config.enable_user_pw = user_pw.strip().lower() == "true"
    if not config.security_policies:
        config.security_policies = [ua.SecurityPolicyType.NoSecurity]
    return config
