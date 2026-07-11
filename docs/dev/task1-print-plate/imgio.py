"""
Windows + 비-ASCII(한글 등) 경로에서 cv2.imread/imwrite가 실패하는 문제를 우회하는 유틸리티.

OpenCV의 cv2.imread/imwrite는 내부적으로 좁은 문자열(codepage) API를 사용하므로
경로에 한글 등 비-ASCII 문자가 포함되면 파일을 찾지 못한다 (본 프로젝트 경로 자체가
"...26년 AP Claude Play Ground..."로 한글을 포함하므로 이 우회가 필수적이다).
numpy.fromfile/tofile + cv2.imdecode/imencode 조합으로 우회한다.
"""

import numpy as np
import cv2


def imread_unicode(path, flags=cv2.IMREAD_COLOR):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, flags)


def imwrite_unicode(path, img, ext=".png"):
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"이미지 인코딩 실패: {path}")
    buf.tofile(path)
    return True
