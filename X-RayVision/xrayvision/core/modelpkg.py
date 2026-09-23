"""
模型檔 (.xrvmodel) 格式 (規劃書 PLAN-002 第 5.2 節)

ZIP 檔，內含：
  model.json   模型描述：format、product、model_id、version、module_id、task、input、output、
               training (訓練資料摘要)、metrics (驗證指標)、created_at、files {"model.onnx": SHA-256}
  model.sig    model.json 的 Ed25519 簽章 (原廠以更新簽章金鑰簽署)
  model.onnx   ONNX 模型

模型參照在配方中寫成 "模型代碼@版本"，例如 "void_unet@1.0.0"。
"""
import hashlib
import json
import re
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

FORMAT = "xrv-model/1"
REF_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,40}@\d+\.\d+\.\d+$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
MAX_ONNX_BYTES = 200 << 20


class ModelPackageError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def ref(model_id, version):
    return f"{model_id}@{version}"


def split_ref(r):
    if not r or not REF_PATTERN.match(r):
        raise ModelPackageError("invalid_model_ref", r)
    mid, ver = r.split("@")
    return mid, ver


def verify(path, public_key_path):
    """驗證簽章、格式與模型雜湊；回傳 (meta, onnx_bytes)"""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ModelPackageError("model_package_invalid")
    with z:
        try:
            raw = z.read("model.json")
            sig = z.read("model.sig")
            info = z.getinfo("model.onnx")
        except KeyError:
            raise ModelPackageError("model_package_invalid")
        pub = serialization.load_pem_public_key(open(public_key_path, "rb").read())
        try:
            pub.verify(sig, raw)
        except InvalidSignature:
            raise ModelPackageError("model_signature_invalid")
        try:
            meta = json.loads(raw)
        except ValueError:
            raise ModelPackageError("model_package_invalid")
        if meta.get("format") != FORMAT or meta.get("product") != "xrayvision":
            raise ModelPackageError("model_package_invalid")
        if not ID_PATTERN.match(str(meta.get("model_id", ""))) or not VERSION_PATTERN.match(str(meta.get("version", ""))):
            raise ModelPackageError("model_package_invalid", "model_id/version")
        if info.file_size > MAX_ONNX_BYTES:
            raise ModelPackageError("model_package_invalid", "size")
        data = z.read("model.onnx")
        if hashlib.sha256(data).hexdigest() != (meta.get("files") or {}).get("model.onnx"):
            raise ModelPackageError("model_hash_mismatch")
    return meta, data


def build(out_path, meta, onnx_bytes, private_key_path):
    """原廠端：寫入雜湊並簽章，產生 .xrvmodel"""
    key = serialization.load_pem_private_key(open(private_key_path, "rb").read(), password=None)
    meta = dict(meta, format=FORMAT, product="xrayvision",
                files={"model.onnx": hashlib.sha256(onnx_bytes).hexdigest()})
    raw = json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("model.json", raw)
        z.writestr("model.sig", key.sign(raw))
        z.writestr("model.onnx", onnx_bytes)
    return meta
