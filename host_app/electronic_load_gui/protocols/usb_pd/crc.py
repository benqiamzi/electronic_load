from zlib import crc32


def calculate_crc32(header_and_body: bytes) -> int:
    """Calculate the USB-PD CRC over the Message Header and body."""
    # USB PD R3.2 V1.1 §5.6.2: polynomial 0x04C11DB7, reflected
    # 0xEDB88320, initial value and final XOR 0xFFFFFFFF, input/output
    # reflected. zlib.crc32 implements these parameters. DRPD stores
    # the received result in little-endian byte order.
    return crc32(header_and_body)
