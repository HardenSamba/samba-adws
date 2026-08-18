import struct

class MultiByteInt31:
    def __init__(self, value: int = 0):
        self.value: int = value

    def to_bytes(self) -> bytes:
        res: list = []
        temp_val: int = self.value
        while temp_val > 0x7F:
            byte: int = (temp_val & 0x7F) | 0x80
            res.append(byte)
            temp_val >>= 7
        res.append(temp_val & 0x7F)
        return bytes(res)

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def parse(cls, fp) -> 'MultiByteInt31':
        v: int = 0
        for pos in range(5):
            b: bytes = fp.read(1)
            if not b:
                break
            val: int = struct.unpack(b'<B', b)[0]
            v |= (val & 0x7F) << (7 * pos)
            if not (val & 0x80):
                break
        return cls(v)


class Utf8String:
    def __init__(self, value: str = ''):
        self.value: str = value
        if isinstance(value, bytes):
            self.value = value.decode('utf-8')

    def to_bytes(self) -> bytes:
        encoded_data: bytes = self.value.encode('utf-8')
        length_prefix: bytes = MultiByteInt31(len(encoded_data)).to_bytes()
        return length_prefix + encoded_data

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def parse(cls, fp) -> 'Utf8String':
        length_obj = MultiByteInt31.parse(fp)
        data: bytes = fp.read(length_obj.value)
        return cls(data.decode('utf-8'))


class Decimal:
    def __init__(self, sign: bool, high: int, low: int, scale: int):
        if not 0 <= scale <= 28:
            raise ValueError(f'scale {scale} out of range (0-28)')
        self.sign: bool = sign
        self.high: int = high
        self.low: int = low
        self.scale: int = scale

    def to_bytes(self) -> bytes:
        bt: bytes = b''
        sign_byte: int = 0x80 if self.sign else 0x00
        bt += struct.pack(b'<H', 0)
        bt += struct.pack(b'<B', self.scale)
        bt += struct.pack(b'<B', sign_byte)
        bt += struct.pack(b'<I', self.high)
        bt += struct.pack(b'<Q', self.low)
        return bt

    def __str__(self) -> str:
        raw_val: int = (self.high * 2**64) + self.low
        s_val: str = str(raw_val)
        if self.scale > 0:
            integer_part = s_val[:-self.scale] or '0'
            frac_part = s_val[-self.scale:].rjust(self.scale, '0')
            number = f"{integer_part}.{frac_part}"
        else:
            number = s_val
        return f"-{number}" if self.sign else number

    @classmethod
    def parse(cls, fp) -> 'Decimal':
        fp.read(2)
        scale: int = struct.unpack(b'<B', fp.read(1))[0]
        sign_raw: int = struct.unpack(b'<B', fp.read(1))[0]
        high: int = struct.unpack(b'<I', fp.read(4))[0]
        low: int = struct.unpack(b'<Q', fp.read(8))[0]
        return cls(bool(sign_raw & 0x80), high, low, scale)
