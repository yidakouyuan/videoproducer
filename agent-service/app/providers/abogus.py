"""
A-Bogus 签名生成器。

用于为抖音 Web API 请求生成 `a_bogus` 参数。
原始实现来自：
  https://github.com/Evil0ctal/Douyin_TikTok_Download_API
  https://github.com/JoeanAmier/TikTokDownloader
均遵循 GNU GPLv3 授权。

依赖：gmssl（pip install gmssl）
"""
from __future__ import annotations

from random import choice, randint
from random import random as _random
from re import compile
from time import time as _time
from urllib.parse import urlencode

from gmssl import func, sm3

__all__ = ["ABogus"]


class ABogus:
    _filter = compile(r"%([0-9A-F]{2})")
    _end_string = "cus"
    _browser_default = "1536|742|1536|864|0|0|0|0|1536|864|1536|864|1536|742|24|24|MacIntel"
    _reg_init = [
        1937774191, 1226093241, 388252375, 3666478592,
        2842636476, 372324522, 3817729613, 2969243214,
    ]
    # UA 编码对应 Chrome/90.0.4430.212（与 ua_code 列表强绑定，勿随意更换 User-Agent）
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/90.0.4430.212 Safari/537.36"
    )
    _ua_code = [
        76, 98, 15, 131, 97, 245, 224, 133, 122, 199,
        241, 166, 79, 34, 90, 191, 128, 126, 122, 98,
        66, 11, 14, 40, 49, 110, 110, 173, 67, 96, 138, 252,
    ]
    # Base64 变体字符集
    _S4 = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"

    def __init__(self, platform: str = "Win32") -> None:
        self._reg: list[int] = self._reg_init[:]
        self._chunk: list[int] = []
        self._size: int = 0
        self._browser = self._gen_browser(platform)
        self._browser_len = len(self._browser)
        self._browser_code = [ord(c) for c in self._browser]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_value(self, url_params: dict | str, method: str = "GET") -> str:
        """根据 URL 参数和请求方法生成 a_bogus 值。"""
        param_str = urlencode(url_params) if isinstance(url_params, dict) else url_params
        s1 = self._gen_s1()
        s2 = self._gen_s2(param_str, method)
        return self._encode(s1 + s2)

    # ------------------------------------------------------------------
    # SM3 哈希
    # ------------------------------------------------------------------

    @staticmethod
    def _sm3(data: str | list) -> list[int]:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        h = sm3.sm3_hash(func.bytes_to_list(raw))
        return [int(h[i: i + 2], 16) for i in range(0, len(h), 2)]

    @classmethod
    def _sm3x2(cls, data: str | list) -> list[int]:
        return cls._sm3(cls._sm3(data if isinstance(data, str) else data))

    def _param_code(self, params: str) -> list[int]:
        return self._sm3x2(params + self._end_string)

    def _method_code(self, method: str) -> list[int]:
        return self._sm3x2(method + self._end_string)

    # ------------------------------------------------------------------
    # SM3 压缩函数（用于内部哈希）
    # ------------------------------------------------------------------

    @staticmethod
    def _de(e: int, r: int) -> int:
        r %= 32
        return ((e << r) & 0xFFFFFFFF) | (e >> (32 - r))

    @staticmethod
    def _pe(e: int) -> int:
        return 2043430169 if 0 <= e < 16 else 2055708042

    @staticmethod
    def _he(e: int, r: int, t: int, n: int) -> int:
        if 0 <= e < 16:
            return (r ^ t ^ n) & 0xFFFFFFFF
        return (r & t | r & n | t & n) & 0xFFFFFFFF

    @staticmethod
    def _ve(e: int, r: int, t: int, n: int) -> int:
        if 0 <= e < 16:
            return (r ^ t ^ n) & 0xFFFFFFFF
        return (r & t | ~r & n) & 0xFFFFFFFF

    def _expand(self, a: list[int]) -> list[int]:
        r = [0] * 132
        for t in range(16):
            r[t] = (a[4*t] << 24) | (a[4*t+1] << 16) | (a[4*t+2] << 8) | a[4*t+3]
            r[t] &= 0xFFFFFFFF
        for n in range(16, 68):
            x = r[n-16] ^ r[n-9] ^ self._de(r[n-3], 15)
            x = x ^ self._de(x, 15) ^ self._de(x, 23)
            r[n] = (x ^ self._de(r[n-13], 7) ^ r[n-6]) & 0xFFFFFFFF
        for n in range(68, 132):
            r[n] = (r[n-68] ^ r[n-64]) & 0xFFFFFFFF
        return r

    def _compress(self, a: list[int]) -> None:
        f = self._expand(a)
        i = self._reg[:]
        for o in range(64):
            c = self._de(i[0], 12) + i[4] + self._de(self._pe(o), o)
            c &= 0xFFFFFFFF
            c = self._de(c, 7)
            s = (c ^ self._de(i[0], 12)) & 0xFFFFFFFF
            u = (self._he(o, i[0], i[1], i[2]) + i[3] + s + f[o+68]) & 0xFFFFFFFF
            b = (self._ve(o, i[4], i[5], i[6]) + i[7] + c + f[o]) & 0xFFFFFFFF
            i[3] = i[2]; i[2] = self._de(i[1], 9); i[1] = i[0]; i[0] = u
            i[7] = i[6]; i[6] = self._de(i[5], 19); i[5] = i[4]
            i[4] = (b ^ self._de(b, 9) ^ self._de(b, 17)) & 0xFFFFFFFF
        for l in range(8):
            self._reg[l] = (self._reg[l] ^ i[l]) & 0xFFFFFFFF

    # ------------------------------------------------------------------
    # RC4 加密
    # ------------------------------------------------------------------

    @staticmethod
    def _rc4(plaintext: str, key: str) -> str:
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + ord(key[i % len(key)])) % 256
            s[i], s[j] = s[j], s[i]
        i = j = 0
        out = []
        for ch in plaintext:
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            out.append(chr(s[(s[i] + s[j]) % 256] ^ ord(ch)))
        return "".join(out)

    # ------------------------------------------------------------------
    # 随机列表生成
    # ------------------------------------------------------------------

    @staticmethod
    def _rand_list(a=None, b=170, c=85, d=0, e=0, f=0, g=0) -> list[int]:
        r = a or (_random() * 10000)
        v = [r, int(r) & 255, int(r) >> 8]
        v += [v[1] & b | d, v[1] & c | e, v[2] & b | f, v[2] & c | g]
        return v[-4:]

    def _gen_s1(self, r1=None, r2=None, r3=None) -> str:
        fc = lambda *a: "".join(chr(x) for x in a)
        return (
            fc(*self._rand_list(r1, 170, 85, 1, 2, 5, 45 & 170))
            + fc(*self._rand_list(r2, 170, 85, 1, 0, 0, 0))
            + fc(*self._rand_list(r3, 170, 85, 1, 0, 5, 0))
        )

    # ------------------------------------------------------------------
    # 核心数据块生成
    # ------------------------------------------------------------------

    def _gen_s2(self, url_params: str, method: str, st: int = 0, et: int = 0) -> str:
        st = st or int(_time() * 1000)
        et = et or (st + randint(4, 8))
        p = self._param_code(url_params)
        m = self._method_code(method)
        ua = self._ua_code
        bl = self._browser_len

        lst = [
            44, (et >> 24) & 255, 0, 0, 0, 0, 24,
            p[21], m[21], 0, ua[23], (et >> 16) & 255,
            0, 0, 0, 1, 0, 239, p[22], m[22], ua[24],
            (et >> 8) & 255, 0, 0, 0, 0, (et >> 0) & 255,
            0, 0, 14, (st >> 24) & 255, (st >> 16) & 255,
            0, (st >> 8) & 255, (st >> 0) & 255, 3,
            (int(et / 256**4)) & 255, 1,
            (int(st / 256**4)) & 255, 1, bl, 0, 0, 0,
        ]
        xor = 0
        for x in lst:
            xor ^= x
        lst.extend(self._browser_code)
        lst.append(xor)
        return self._rc4("".join(chr(x) for x in lst), "y")

    # ------------------------------------------------------------------
    # Base64 变体编码
    # ------------------------------------------------------------------

    @classmethod
    def _encode(cls, s: str) -> str:
        r = []
        for i in range(0, len(s), 3):
            if i + 2 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i+1]) << 8) | ord(s[i+2])
            elif i + 1 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i+1]) << 8)
            else:
                n = ord(s[i]) << 16
            for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
                if j == 6 and i + 1 >= len(s):
                    break
                if j == 0 and i + 2 >= len(s):
                    break
                r.append(cls._S4[(n & k) >> j])
        r.append("=" * ((4 - len(r) % 4) % 4))
        return "".join(r)

    # ------------------------------------------------------------------
    # 浏览器信息生成
    # ------------------------------------------------------------------

    @staticmethod
    def _gen_browser(platform: str = "Win32") -> str:
        iw = randint(1280, 1920)
        ih = randint(720, 1080)
        ow = randint(iw, 1920)
        oh = randint(ih, 1080)
        return "|".join(str(x) for x in [
            iw, ih, ow, oh, 0, choice((0, 30)), 0, 0,
            ow, oh, ow, oh, iw, ih, 24, 24, platform,
        ])
