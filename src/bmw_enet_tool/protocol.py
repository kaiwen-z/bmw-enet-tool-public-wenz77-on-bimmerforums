import struct

TESTER = 0xF4
DYN_H = 0xF3
DYN_L = 0x00


def hsfz(src, dst, uds: bytes) -> bytes:
    body = bytes([src, dst]) + uds
    return struct.pack(">I", len(body)) + b"\x00\x01" + body


def parse_hsfz(buf: bytes):
    if len(buf) < 6:
        return None
    n = struct.unpack(">I", buf[0:4])[0]
    msg_type = struct.unpack(">H", buf[4:6])[0]
    if len(buf) < 6 + n:
        return None
    body = buf[6 : 6 + n]
    if len(body) < 2:
        return None
    # msg_type 0x0001 = real application data from ECU
    # msg_type 0x0002 = gateway echo/acknowledgment — must be ignored
    return body[0], body[1], body[2:], 6 + n, msg_type  # src, dst, uds, consumed, type
