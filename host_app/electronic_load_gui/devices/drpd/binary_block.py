from __future__ import annotations


# The current DRPD firmware stores up to 5600 uint16 pulses and 262 decoded bytes.
DEFAULT_MAX_PAYLOAD_BYTES = 32 + 2 * 5600 + 262


class BinaryBlockError(ValueError):
    """Malformed SCPI definite-length binary block."""


class BinaryBlockParser:
    """Incrementally extract payloads from #N<length><payload><LF> blocks."""

    def __init__(self, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        if not 0 <= max_payload_bytes <= 999_999_999:
            raise ValueError("max_payload_bytes must fit the SCPI length field")
        self._max_payload_bytes = max_payload_bytes
        self.reset()

    def reset(self) -> None:
        self._buffer = bytearray()
        self._header_size: int | None = None
        self._block_size: int | None = None

    @property
    def has_pending_data(self) -> bool:
        return bool(self._buffer)

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        blocks = []
        consumed = 0
        try:
            while consumed < len(self._buffer):
                if self._buffer[consumed] != ord("#"):
                    raise BinaryBlockError("二进制块缺少 # 起始符")
                if len(self._buffer) - consumed < 2:
                    break
                if self._header_size is None:
                    digits = self._buffer[consumed + 1] - ord("0")
                    if digits == 0:
                        raise BinaryBlockError("不支持 #0 不定长块")
                    if not 1 <= digits <= 9:
                        raise BinaryBlockError("二进制块长度位数必须为 1～9")
                    self._header_size = 2 + digits

                payload_start = consumed + self._header_size
                length_field = self._buffer[consumed + 2 : payload_start]
                if length_field and not length_field.isdigit():
                    raise BinaryBlockError("二进制块长度字段必须是十进制数字")
                if len(self._buffer) < payload_start:
                    break
                if self._block_size is None:
                    payload_size = int(length_field)
                    if payload_size > self._max_payload_bytes:
                        raise BinaryBlockError(f"二进制块载荷超过上限 {self._max_payload_bytes} 字节")
                    self._block_size = self._header_size + payload_size + 1

                terminator = consumed + self._block_size - 1
                if terminator >= len(self._buffer):
                    break
                if self._buffer[terminator] != 0x0A:
                    raise BinaryBlockError("二进制块末尾缺少 LF")
                blocks.append(bytes(self._buffer[payload_start:terminator]))
                consumed = terminator + 1
                self._header_size = None
                self._block_size = None
        except BinaryBlockError:
            self.reset()
            raise
        if consumed:
            del self._buffer[:consumed]
        return blocks
