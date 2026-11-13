import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from triade.federation.exchange import Ed25519EnvelopeAuthenticator, FederatedEnvelope


def test_ed25519_sign_verify_and_tamper() -> None:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    auth = Ed25519EnvelopeAuthenticator(lambda _: public_pem, lambda _: private_pem)
    now = int(time.time())
    unsigned = FederatedEnvelope(
        "m", "a", "b", "c", "return_evidence", "n", now, now + 10, {"x": 1}
    )
    signed = auth.sign(unsigned)
    assert auth.verify(signed)
    tampered = FederatedEnvelope(**{**signed.to_dict(), "payload": {"x": 2}})
    assert not auth.verify(tampered)
