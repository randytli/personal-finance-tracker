"""Authenticated external recovery bundle: pg_dump plus its restore manifest."""
import argparse
import getpass
import json
import os
from pathlib import Path
import struct
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from api.backup import digest

MAGIC = b"PFTENC2\n"
CHUNK = 1024 * 1024
MAX_MANIFEST = 1024 * 1024


def key(password, salt):
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def encrypt(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise RuntimeError("encrypted destination already exists")
    manifest_bytes = source.with_suffix(".json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if (len(manifest_bytes) > MAX_MANIFEST or manifest["sha256"] != digest(source)
            or manifest["size"] != source.stat().st_size):
        raise RuntimeError("source archive checksum or size mismatch")
    password = getpass.getpass("External-copy password: ")
    if password != getpass.getpass("Repeat password: ") or not password:
        raise RuntimeError("passwords do not match")
    salt, nonce = os.urandom(16), os.urandom(12)
    payload_size = 4 + len(manifest_bytes) + manifest["size"]
    header = MAGIC + salt + nonce + struct.pack(">Q", payload_size)
    encoder = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce)).encryptor()
    encoder.authenticate_additional_data(header)
    # Private staging also avoids deleting another operation's temporary file
    # when an exclusive open fails. Link publication never overwrites a copy.
    with tempfile.TemporaryDirectory(prefix=".pft-encrypt-", dir=destination.parent) as staging:
        temporary = Path(staging) / "bundle"
        with source.open("rb") as data, temporary.open("xb") as output:
            os.chmod(temporary, 0o600)
            output.write(header)
            output.write(encoder.update(struct.pack(">I", len(manifest_bytes)) + manifest_bytes))
            for block in iter(lambda: data.read(CHUNK), b""):
                output.write(encoder.update(block))
            output.write(encoder.finalize() + encoder.tag)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
    return {"encrypted_file": str(destination), "sha256": digest(destination)}


def decrypt(source, destination):
    source, destination = Path(source), Path(destination)
    manifest_path = destination.with_suffix(".json")
    if destination == manifest_path or destination.exists() or manifest_path.exists():
        raise RuntimeError("restore destination or manifest already exists")
    with source.open("rb") as data:
        header_size = len(MAGIC) + 16 + 12 + 8
        header = data.read(header_size)
        if len(header) != header_size or not header.startswith(MAGIC):
            raise RuntimeError("invalid recovery bundle (dump and manifest required)")
        salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[len(MAGIC)+16:-8]
        size = struct.unpack(">Q", header[-8:])[0]
        if size < 4 or source.stat().st_size != header_size + size + 16:
            raise RuntimeError("invalid encrypted archive size")
        data.seek(-16, 2)
        tag = data.read(16)
        data.seek(header_size)
        decoder = Cipher(algorithms.AES(key(getpass.getpass("External-copy password: "), salt)),
                         modes.GCM(nonce, tag)).decryptor()
        decoder.authenticate_additional_data(header)
        manifest_size = struct.unpack(">I", decoder.update(data.read(4)))[0]
        if manifest_size > MAX_MANIFEST or manifest_size > size - 4:
            raise RuntimeError("invalid recovery manifest size")
        manifest_bytes = decoder.update(data.read(manifest_size))
        # Do not parse or publish unauthenticated metadata or plaintext.
        with tempfile.TemporaryDirectory(prefix=".pft-decrypt-", dir=destination.parent) as staging:
            temporary, metadata_temp = Path(staging) / "dump", Path(staging) / "manifest"
            with temporary.open("xb") as output:
                os.chmod(temporary, 0o600)
                remaining = size - 4 - manifest_size
                while remaining:
                    block = data.read(min(CHUNK, remaining))
                    if not block:
                        raise RuntimeError("truncated encrypted archive")
                    output.write(decoder.update(block))
                    remaining -= len(block)
                output.write(decoder.finalize())
                output.flush()
                os.fsync(output.fileno())
            manifest = json.loads(manifest_bytes)
            if manifest["sha256"] != digest(temporary) or manifest["size"] != temporary.stat().st_size:
                raise RuntimeError("recovered archive checksum or size mismatch")
            metadata_temp.write_bytes(manifest_bytes)
            os.chmod(metadata_temp, 0o600)
            os.link(metadata_temp, manifest_path)
            try:
                os.link(temporary, destination)
            except BaseException:
                manifest_path.unlink()
                raise
    return {"decrypted_file": str(destination), "manifest": str(manifest_path),
            "sha256": digest(destination)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("encrypt", "decrypt"))
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    print(json.dumps(encrypt(args.source, args.destination) if args.action == "encrypt"
                     else decrypt(args.source, args.destination)))


if __name__ == "__main__":
    main()
