import bz2
import gzip
import io
import json
import lzma
import os
import struct
import tarfile

import fdt

from .. import settings as app_settings
from .base import BaseMetadataExtractor
from .exceptions import (
    DecompressionLimitExceeded,
    ExtractionError,
    UnsupportedImageError,
)

try:
    import lz4.frame as lz4frame

    _LZ4_AVAILABLE = True
except ImportError:
    _LZ4_AVAILABLE = False


_X86_SUFFIXES = (".img", ".vdi", ".vmdk")

DTB_MAGIC = b"\xd0\x0d\xfe\xed"
DTB_MIN_SIZE = 64
DTB_MAX_SIZE = 10 * 1024 * 1024
UIMAGE_MAGIC = b"\x27\x05\x19\x56"
UIMAGE_HEADER_SIZE = 64
_CHUNK_SIZE = 64 * 1024
FWIMAGE_MAGIC = 0x46577830
FWIMAGE_INFO = 1
TRAILER_FORMAT = ">IIB3sI"
TRAILER_SIZE = struct.calcsize(TRAILER_FORMAT)
HEADER_FORMAT = ">II"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
_CRC32_POLYNOMIAL = 0xEDB88320


def _crc32_filltable():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c >> 1) ^ _CRC32_POLYNOMIAL) if (c & 1) else (c >> 1)
        table.append(c)
    return table


_CRC32_TABLE = _crc32_filltable()


def _crc32_block(val, data):
    for byte in data:
        val = _CRC32_TABLE[(val & 0xFF) ^ byte] ^ (val >> 8)
    return val


def _extract_fwtool_metadata(firmware_path):
    with open(firmware_path, "rb") as f:
        data = f.read()
    file_size = len(data)
    offset = file_size - TRAILER_SIZE
    while offset >= 0:
        trailer_data = data[offset : offset + TRAILER_SIZE]
        if len(trailer_data) < TRAILER_SIZE:
            break
        magic, crc32_val, type_val, _pad, size = struct.unpack(
            TRAILER_FORMAT, trailer_data
        )
        if magic != FWIMAGE_MAGIC:
            offset -= 1
            continue
        data_start = offset - (size - TRAILER_SIZE)
        data_end = offset
        if data_start < 0:
            offset -= 1
            continue
        if _crc32_block(0xFFFFFFFF, data[:data_end]) != crc32_val:
            offset = data_start
            continue
        if type_val == FWIMAGE_INFO:
            metadata_bytes = data[data_start + HEADER_SIZE : data_end]
            try:
                return json.loads(metadata_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                offset = data_start
                continue
        offset = data_start
    return None


def _parse_supported_devices(meta):
    if meta.get("compat_version", "1.0") != "1.0":
        return meta.get("new_supported_devices", [])
    return meta.get("supported_devices", [])


def _strip_uimage_header(data):
    if data[:4] == UIMAGE_MAGIC and len(data) > UIMAGE_HEADER_SIZE:
        payload_size = struct.unpack_from(">I", data, 12)[0]
        return data[UIMAGE_HEADER_SIZE : UIMAGE_HEADER_SIZE + payload_size]
    return data


def _check_limits(decompressed, compressed):
    if decompressed > app_settings.MAX_DECOMPRESSED_BYTES:
        raise DecompressionLimitExceeded(
            f"Decompressed size exceeded hard limit of "
            f"{app_settings.MAX_DECOMPRESSED_BYTES // (1024 * 1024)}MB."
        )
    if (
        compressed > 0
        and (decompressed / compressed) > app_settings.MAX_DECOMPRESSED_RATIO
    ):
        raise DecompressionLimitExceeded(
            f"Compression ratio exceeds limit of "
            f"{app_settings.MAX_DECOMPRESSED_RATIO}:1."
        )


def _try_gzip(data):
    if data[:2] != b"\x1f\x8b":
        return None
    chunks, total = [], 0
    compressed = len(data)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            while True:
                chunk = gz.read(_CHUNK_SIZE)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                _check_limits(total, compressed)
    except DecompressionLimitExceeded:
        raise
    except Exception:
        return None
    return b"".join(chunks) or None


def _try_xz(data):
    if data[:6] != b"\xfd7zXZ\x00":
        return None
    chunks, total = [], 0
    compressed = len(data)
    dec = lzma.LZMADecompressor(
        format=lzma.FORMAT_XZ, memlimit=app_settings.MAX_DECOMPRESSED_BYTES
    )
    try:
        offset = 0
        while offset < len(data) and not dec.eof:
            chunk = dec.decompress(data[offset : offset + _CHUNK_SIZE])
            offset += _CHUNK_SIZE
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                _check_limits(total, compressed)
    except DecompressionLimitExceeded:
        raise
    except Exception:
        return None
    return b"".join(chunks) or None


def _try_lzma(data):
    if data[0:1] != b"\x5d":
        return None
    chunks, total = [], 0
    compressed = len(data)
    try:
        dec = lzma.LZMADecompressor(
            format=lzma.FORMAT_ALONE,
            memlimit=app_settings.MAX_DECOMPRESSED_BYTES,
        )
        offset = 0
        while offset < len(data) and not dec.eof:
            chunk = dec.decompress(data[offset : offset + _CHUNK_SIZE])
            offset += _CHUNK_SIZE
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                _check_limits(total, compressed)
    except DecompressionLimitExceeded:
        raise
    except Exception:
        return None
    return b"".join(chunks) or None


def _try_bz2(data):
    if data[:3] != b"BZh":
        return None
    chunks, total = [], 0
    compressed = len(data)
    dec = bz2.BZ2Decompressor()
    try:
        offset = 0
        while offset < len(data) and not dec.eof:
            chunk = dec.decompress(data[offset : offset + _CHUNK_SIZE])
            offset += _CHUNK_SIZE
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                _check_limits(total, compressed)
    except DecompressionLimitExceeded:
        raise
    except Exception:
        return None
    return b"".join(chunks) or None


def _try_lz4(data):
    if not _LZ4_AVAILABLE:
        return None
    if data[:4] != b"\x04\x22\x4d\x18":
        return None
    chunks, total = [], 0
    compressed = len(data)
    try:
        dec = lz4frame.LZ4FrameDecompressor()
        offset = 0
        while offset < len(data) and not dec.eof:
            chunk = dec.decompress(data[offset : offset + _CHUNK_SIZE])
            offset += _CHUNK_SIZE
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                _check_limits(total, compressed)
    except DecompressionLimitExceeded:
        raise
    except Exception:
        return None
    return b"".join(chunks) or None


def _decompress(data):
    for fn in (_try_gzip, _try_xz, _try_lzma, _try_bz2, _try_lz4):
        result = fn(data)
        if result is not None:
            return result
    return data


def _dtb_from_fit(data):
    offset = 4
    while True:
        pos = data.find(DTB_MAGIC, offset)
        if pos == -1:
            return None
        if pos + 8 > len(data):
            break
        total_size = struct.unpack_from(">I", data, pos + 4)[0]
        if DTB_MIN_SIZE < total_size < DTB_MAX_SIZE:
            end = pos + total_size
            if end <= len(data):
                candidate = data[pos:end]
                try:
                    dt = fdt.parse_dtb(candidate)
                    root = dt.get_node("/")
                    if any(p.name in ("model", "compatible") for p in root.props):
                        return candidate
                except Exception:
                    pass
        offset = pos + 1
    return None


def _locate_dtb(kernel_data):
    offset = 0
    fit_candidate = None
    while True:
        pos = kernel_data.find(DTB_MAGIC, offset)
        if pos == -1:
            break
        if pos + 8 > len(kernel_data):
            break
        total_size = struct.unpack_from(">I", kernel_data, pos + 4)[0]
        if DTB_MIN_SIZE < total_size < DTB_MAX_SIZE:
            end = pos + total_size
            if end <= len(kernel_data):
                candidate = kernel_data[pos:end]
                try:
                    dt = fdt.parse_dtb(candidate)
                    root = dt.get_node("/")
                    prop_names = {p.name for p in root.props}
                    if "model" in prop_names or "compatible" in prop_names:
                        return candidate
                    if fit_candidate is None:
                        try:
                            if dt.get_node("/images") is not None:
                                fit_candidate = candidate
                        except Exception:
                            pass
                except Exception:
                    pass
        offset = pos + 1
    if fit_candidate is not None:
        return _dtb_from_fit(fit_candidate)
    return None


def _prop_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, (list, tuple)) and value:
        return str(value[0]).rstrip("\x00")
    return str(value)


def _prop_strlist(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [s for s in value.split("\x00") if s]
    if isinstance(value, (list, tuple)):
        return [str(s).rstrip("\x00") for s in value if s]
    return [str(value)]


def _metadata_from_dtb(dtb_bytes):
    try:
        dt = fdt.parse_dtb(dtb_bytes)
    except Exception as e:
        raise ExtractionError(f"Failed to parse DTB: {e}")
    root = dt.get_node("/")
    model, compatible = None, []
    for prop in root.props:
        if prop.name == "model":
            model = _prop_str(prop.value)
        elif prop.name == "compatible":
            compatible = _prop_strlist(prop.value)
    return {
        "model": model,
        "compatible": compatible,
        "target": "",
        "version": "",
        "compat_version": "1.0",
        "source": "dtb",
    }


class OpenWrtMetadataExtractor(BaseMetadataExtractor):

    def _detect_image_type(self):
        _, ext = os.path.splitext(self.image_path)
        if ext.lower() in _X86_SUFFIXES:
            raise UnsupportedImageError(f"x86 image type not supported: {ext}")
        if "armsr" in os.path.basename(self.image_path).lower():
            raise UnsupportedImageError("armsr image type not supported")

    def _extract_from_fwtool(self):
        meta = _extract_fwtool_metadata(self.image_path)
        if meta is None:
            raise ExtractionError("No fwtool metadata found in image")
        version = meta.get("version", {})
        return {
            "model": version.get("board", ""),
            "compatible": _parse_supported_devices(meta),
            "target": version.get("target", ""),
            "version": version.get("version", ""),
            "compat_version": meta.get("compat_version", "1.0"),
            "source": "fwtool",
        }

    def extract_from_image(self):
        self._detect_image_type()
        return self._extract_from_fwtool()

    def _read_kernel_bytes(self):
        with open(self.image_path, "rb") as f:
            data = f.read(app_settings.MAX_KERNEL_BYTES)
        return data

    def _read_kernel_from_tar(self):
        try:
            with tarfile.open(self.image_path, "r:*") as tf:
                for member in tf.getmembers():
                    name = member.name.lower()
                    if "kernel" in name or name.endswith(".bin"):
                        f = tf.extractfile(member)
                        if f:
                            return f.read(app_settings.MAX_KERNEL_BYTES)

        except tarfile.TarError:
            pass
        return None

    def extract_from_dtb(self):
        try:
            kernel_data = self._read_kernel_bytes()
        except DecompressionLimitExceeded:
            raise
        except OSError:
            kernel_data = self._read_kernel_from_tar()
            if kernel_data is None:
                raise UnsupportedImageError("Could not read kernel data from image")

        kernel_data = _strip_uimage_header(kernel_data)
        kernel_data = _decompress(kernel_data)

        dtb = _locate_dtb(kernel_data)
        if dtb is None:
            raise UnsupportedImageError("No DTB found in image")

        return _metadata_from_dtb(dtb)

    def extract(self):
        try:
            fwtool_result = self.extract_from_image()
        except UnsupportedImageError:
            raise
        except ExtractionError:
            return self.extract_from_dtb()

        if not fwtool_result.get("compatible") or not fwtool_result.get("model"):
            try:
                dtb_result = self.extract_from_dtb()
                if not fwtool_result.get("model") and dtb_result.get("model"):
                    fwtool_result["model"] = dtb_result["model"]
                if not fwtool_result.get("compatible") and dtb_result.get("compatible"):
                    fwtool_result["compatible"] = dtb_result["compatible"]
            except (ExtractionError, UnsupportedImageError):
                pass

        return fwtool_result
