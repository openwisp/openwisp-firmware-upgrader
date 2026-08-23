import bz2
import gzip
import io
import json
import lzma
import os
import struct
import tarfile
import zlib

import fdt
import lz4.frame as lz4frame
from django.utils.translation import gettext_lazy as _

from .. import settings as app_settings
from .base import BaseMetadataExtractor
from .exceptions import (
    DecompressionLimitExceeded,
    ExtractionError,
    UnsupportedImageError,
)

_VIRTUAL_DISK_IMAGES = (".vdi", ".vmdk")
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


class OpenWrtMetadataExtractor(BaseMetadataExtractor):
    """Extract OpenWrt firmware metadata from the fwtool trailer, falls back to DTB."""

    def _validate_image_type(self):
        name = os.path.basename(self.image_path).lower()
        ext = os.path.splitext(name)[1]
        if ext in _VIRTUAL_DISK_IMAGES:
            raise UnsupportedImageError(
                _("Virtual disk image type not supported: {ext}").format(ext=ext)
            )
        if "x86" in name or "armsr" in name:
            raise UnsupportedImageError(
                _("Unsupported image type: {name}").format(name=name)
            )

    def _extract_fwtool_metadata(self):
        with open(self.image_path, "rb") as f:
            data = f.read(app_settings.MAX_KERNEL_BYTES + 1)
        # must read the full file, not just the tail, the trailer's CRC
        # covers the entire prefix from byte 0, so a partial read can
        # never match a genuine trailer's checksum
        if len(data) > app_settings.MAX_KERNEL_BYTES:
            raise DecompressionLimitExceeded(
                _("Firmware file exceeds limit of {size}.").format(
                    size=self._format_size(app_settings.MAX_KERNEL_BYTES)
                )
            )
        file_size = len(data)
        magic_bytes = struct.pack(">I", FWIMAGE_MAGIC)
        view = memoryview(data)
        offset = file_size - TRAILER_SIZE
        probes = 0
        crc_bytes_checked = 0
        while offset >= 0:
            if probes >= app_settings.MAX_TRAILER_PROBES:
                break
            if crc_bytes_checked >= app_settings.MAX_TRAILER_CRC_BYTES:
                break
            probes += 1
            offset = data.rfind(magic_bytes, 0, offset + len(magic_bytes))
            if offset == -1:
                break
            trailer_data = data[offset : offset + TRAILER_SIZE]
            if len(trailer_data) < TRAILER_SIZE:
                offset -= 1
                continue
            _magic, crc32_val, type_val, _pad, size = struct.unpack(
                TRAILER_FORMAT, trailer_data
            )
            data_start = offset - (size - TRAILER_SIZE)
            data_end = offset
            if data_start >= offset:
                offset -= 1
                continue
            if data_start < 0:
                offset -= 1
                continue
            crc_bytes_checked += data_end
            if zlib.crc32(view[:data_end]) ^ 0xFFFFFFFF != crc32_val:
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

    def _parse_supported_devices(self, meta):
        if meta.get("compat_version", "1.0") != "1.0":
            return meta.get("new_supported_devices", [])
        return meta.get("supported_devices", [])

    def _strip_uimage_header(self, data):
        if data[:4] == UIMAGE_MAGIC and len(data) >= UIMAGE_HEADER_SIZE:
            payload_size = struct.unpack_from(">I", data, 12)[0]
            available_payload = len(data) - UIMAGE_HEADER_SIZE
            if payload_size > available_payload:
                return data
            return data[UIMAGE_HEADER_SIZE : UIMAGE_HEADER_SIZE + payload_size]
        return data

    def _format_size(self, size):
        if size < 1024 * 1024:
            return f"{size}B"
        return f"{size // (1024 * 1024)}MB"

    def _check_limits(self, decompressed, compressed):
        if decompressed > app_settings.MAX_DECOMPRESSED_BYTES:
            raise DecompressionLimitExceeded(
                _("Decompressed size exceeded hard limit of {size}.").format(
                    size=self._format_size(app_settings.MAX_DECOMPRESSED_BYTES)
                )
            )
        if (
            compressed > 0
            and (decompressed / compressed) > app_settings.MAX_DECOMPRESSED_RATIO
        ):
            raise DecompressionLimitExceeded(
                _("Compression ratio exceeds limit of {ratio}:1.").format(
                    ratio=app_settings.MAX_DECOMPRESSED_RATIO
                )
            )

    def _try_gzip(self, data):
        if data[:2] != b"\x1f\x8b":
            return None
        buf, total = bytearray(), 0
        compressed = len(data)
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                while True:
                    chunk = gz.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    total += len(chunk)
                    self._check_limits(total, compressed)
        except DecompressionLimitExceeded:
            raise
        except Exception:
            # Some OpenWrt .img.gz files append fwtool metadata after the gzip stream.
            # Keep any valid decompressed bytes collected before gzip reports trailing data.
            pass
        return bytes(buf) or None

    def _try_decompress(self, data, magic, make_decompressor):
        if magic is not None and data[: len(magic)] != magic:
            return None
        if not data:
            return None
        buf, total = bytearray(), 0
        compressed = len(data)
        try:
            dec = make_decompressor()
            offset = 0
            chunk_in = b""
            while not dec.eof and (offset < len(data) or not dec.needs_input):
                if dec.needs_input:
                    chunk_in = data[offset : offset + _CHUNK_SIZE]
                    offset += _CHUNK_SIZE
                chunk = dec.decompress(chunk_in, max_length=_CHUNK_SIZE)
                chunk_in = b""
                if chunk:
                    buf.extend(chunk)
                    total += len(chunk)
                    self._check_limits(total, compressed)
                elif dec.needs_input and not chunk_in and offset >= len(data):
                    break
        except DecompressionLimitExceeded:
            raise
        except Exception:
            # Decompressors are used as probes; invalid formats are expected misses.
            return None
        return bytes(buf) or None

    def _decompressors(self):
        memlimit = app_settings.MAX_DECOMPRESSED_BYTES
        return [
            (b"\x1f\x8b", self._try_gzip),
            (
                b"\xfd7zXZ\x00",
                lambda d: self._try_decompress(
                    d,
                    b"\xfd7zXZ\x00",
                    lambda: lzma.LZMADecompressor(
                        format=lzma.FORMAT_XZ, memlimit=memlimit
                    ),
                ),
            ),
            (
                b"BZh",
                lambda d: self._try_decompress(
                    d, b"BZh", lambda: bz2.BZ2Decompressor()
                ),
            ),
            (
                b"\x04\x22\x4d\x18",
                lambda d: self._try_decompress(
                    d, b"\x04\x22\x4d\x18", lambda: lz4frame.LZ4FrameDecompressor()
                ),
            ),
        ]

    def _deep_scan_for_dtb(self, data, budget=None):
        if budget is None:
            budget = [app_settings.MAX_DEEP_SCAN_PROBES]
        memlimit = app_settings.MAX_DECOMPRESSED_BYTES
        for magic, decompress_fn in self._decompressors():
            offset = 0
            probes = 0
            while True:
                pos = data.find(magic, offset)
                if (
                    pos == -1
                    or probes >= app_settings.MAX_DEEP_SCAN_PROBES
                    or budget[0] <= 0
                ):
                    break
                probes += 1
                try:
                    decompressed = decompress_fn(data[pos:])
                    if decompressed:
                        dtb = self._locate_dtb(decompressed, budget=budget)
                        if dtb is not None:
                            return dtb
                except DecompressionLimitExceeded:
                    raise
                except Exception:
                    # Deep scan probes arbitrary offsets, so failed candidates are normal.
                    pass
                offset = pos + 1
        # LZMA-alone streams start with a properties byte followed by these
        # dictionary-size values, so rewind one byte from each match
        for dict_sig in (b"\x00\x00\x80\x00", b"\x00\x00\x40\x00", b"\x00\x00\x00\x01"):
            offset = 1
            probes = 0
            while True:
                pos = data.find(dict_sig, offset)
                if (
                    pos == -1
                    or probes >= app_settings.MAX_DEEP_SCAN_PROBES
                    or budget[0] <= 0
                ):
                    break
                probes += 1
                try:
                    decompressed = self._try_decompress(
                        data[pos - 1 :],
                        None,
                        lambda: lzma.LZMADecompressor(
                            format=lzma.FORMAT_ALONE, memlimit=memlimit
                        ),
                    )
                    if decompressed:
                        dtb = self._locate_dtb(decompressed, budget=budget)
                        if dtb is not None:
                            return dtb
                except DecompressionLimitExceeded:
                    raise
                except Exception:
                    # Deep scan probes arbitrary offsets, so failed candidates are normal.
                    pass
                offset = pos + 1
        return None

    def _iterate_dtb_candidates(self, data, start=0, budget=None):
        if budget is None:
            budget = [app_settings.MAX_DEEP_SCAN_PROBES]
        offset = start
        while True:
            pos = data.find(DTB_MAGIC, offset)
            if pos == -1 or pos + 8 > len(data) or budget[0] <= 0:
                return
            budget[0] -= 1
            total_size = struct.unpack_from(">I", data, pos + 4)[0]
            end = pos + total_size
            if DTB_MIN_SIZE < total_size < DTB_MAX_SIZE and end <= len(data):
                candidate = data[pos:end]
                try:
                    yield candidate, fdt.parse_dtb(candidate)
                except Exception:
                    # DTB magic may appear in invalid candidate data
                    pass
            offset = pos + 1

    def _dtb_from_fit(self, data, budget=None):
        for candidate, dt in self._iterate_dtb_candidates(data, start=4, budget=budget):
            try:
                root = dt.get_node("/")
                if any(p.name in ("model", "compatible") for p in root.props):
                    return candidate
            except Exception:
                pass
        return None

    def _locate_dtb(self, kernel_data, budget=None):
        if budget is None:
            budget = [app_settings.MAX_DEEP_SCAN_PROBES]
        fit_candidate = None
        for candidate, dt in self._iterate_dtb_candidates(kernel_data, budget=budget):
            try:
                root = dt.get_node("/")
                prop_names = {p.name for p in root.props}
                if "model" in prop_names or "compatible" in prop_names:
                    return candidate
                if fit_candidate is None:
                    try:
                        if dt.get_node("/images") is not None:
                            fit_candidate = candidate
                    except Exception:
                        # Not every valid DTB candidate is a FIT image
                        pass
            except Exception:
                pass
        if fit_candidate is not None:
            return self._dtb_from_fit(fit_candidate, budget=budget)
        return None

    def _prop_str(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value.rstrip("\x00")
        if isinstance(value, (list, tuple)) and value:
            return str(value[0]).rstrip("\x00")
        return str(value)

    def _prop_strlist(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [s for s in value.split("\x00") if s]
        if isinstance(value, (list, tuple)):
            return [str(s).rstrip("\x00") for s in value if s]
        return [str(value)]

    def _metadata_from_dtb(self, dtb_bytes):
        try:
            dt = fdt.parse_dtb(dtb_bytes)
        except Exception as e:
            raise ExtractionError(f"Failed to parse DTB: {e}")
        root = dt.get_node("/")
        model, compatible = None, []
        # model uses prop.value (singel string), compatible uses prop.data
        # (full list), don't swap these
        for prop in root.props:
            if prop.name == "model":
                model = self._prop_str(prop.value)
            elif prop.name == "compatible":
                compatible = self._prop_strlist(prop.data)
        return {
            "model": model,
            "compatible": compatible,
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }

    def _extract_from_fwtool(self):
        meta = self._extract_fwtool_metadata()
        if meta is None:
            raise ExtractionError("No fwtool metadata found in image")
        if not isinstance(meta, dict):
            raise ExtractionError("Malformed fwtool metadata")
        version = meta.get("version", {})
        if not isinstance(version, dict):
            raise ExtractionError("Malformed fwtool metadata")
        return {
            "model": version.get("board", ""),
            "compatible": self._parse_supported_devices(meta),
            "target": version.get("target", ""),
            "version": version.get("version", ""),
            "compat_version": meta.get("compat_version", "1.0"),
            "source": "fwtool",
        }

    def extract_from_image(self):
        self._validate_image_type()
        return self._extract_from_fwtool()

    def _read_kernel_bytes(self):
        with open(self.image_path, "rb") as f:
            data = f.read(app_settings.MAX_KERNEL_BYTES + 1)
        if len(data) > app_settings.MAX_KERNEL_BYTES:
            raise DecompressionLimitExceeded(
                _("Kernel data exceeds limit of {size}").format(
                    size=self._format_size(app_settings.MAX_KERNEL_BYTES)
                )
            )
        return data

    def _read_kernel_from_tar(self):
        raw = self._read_kernel_bytes()
        decompressed = None
        for _magic, decompress_fn in self._decompressors():
            decompressed = decompress_fn(raw)
            if decompressed is not None:
                break
        tar_bytes = decompressed if decompressed is not None else raw
        try:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
                for member in tf.getmembers():
                    name = member.name.lower()
                    if "kernel" in name or name.endswith(".bin"):
                        f = tf.extractfile(member)
                        if f:
                            data = f.read(app_settings.MAX_KERNEL_BYTES + 1)
                            if len(data) > app_settings.MAX_KERNEL_BYTES:
                                raise DecompressionLimitExceeded(
                                    _("Kernel data exceeds limit of {size}.").format(
                                        size=self._format_size(
                                            app_settings.MAX_KERNEL_BYTES
                                        )
                                    )
                                )
                            return data
        except tarfile.TarError:
            pass
        return None

    def _try_extract_dtb_from_kernel(self, kernel_data):
        memlimit = app_settings.MAX_DECOMPRESSED_BYTES
        stripped = self._strip_uimage_header(kernel_data)
        decompressed = None
        for _magic, decompress_fn in self._decompressors():
            decompressed = decompress_fn(stripped)
            if decompressed is not None:
                break
        if decompressed is None:
            decompressed = self._try_decompress(
                stripped,
                None,
                lambda: lzma.LZMADecompressor(
                    format=lzma.FORMAT_ALONE, memlimit=memlimit
                ),
            )
        if decompressed is None:
            decompressed = stripped
        budget = [app_settings.MAX_DEEP_SCAN_PROBES]
        dtb = self._locate_dtb(decompressed, budget=budget)
        if dtb is None:
            dtb = self._deep_scan_for_dtb(decompressed, budget=budget)
        return dtb

    def extract_from_dtb(self):
        kernel_data = None
        try:
            kernel_data = self._read_kernel_bytes()
        except DecompressionLimitExceeded:
            raise
        except OSError:
            pass
        if kernel_data is not None:
            dtb = self._try_extract_dtb_from_kernel(kernel_data)
            if dtb is not None:
                return self._metadata_from_dtb(dtb)
        tar_kernel = self._read_kernel_from_tar()
        if tar_kernel is not None:
            dtb = self._try_extract_dtb_from_kernel(tar_kernel)
            if dtb is not None:
                return self._metadata_from_dtb(dtb)
        raise UnsupportedImageError(_("No DTB found in image"))

    def extract(self):
        try:
            fwtool_result = self.extract_from_image()
        except (UnsupportedImageError, DecompressionLimitExceeded):
            raise
        except ExtractionError:
            return self.extract_from_dtb()
        # DTB overrides fwtool model with human-readable label; compatible is
        # backfilled only if missing
        try:
            dtb_result = self.extract_from_dtb()
            if dtb_result.get("model"):
                fwtool_result["model"] = dtb_result["model"]
            if not fwtool_result.get("compatible") and dtb_result.get("compatible"):
                fwtool_result["compatible"] = dtb_result["compatible"]
        except ExtractionError:
            pass
        return fwtool_result
