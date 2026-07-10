# Progress Log — 08 Printing ML

## 현재 상태 요약 (2026-07-10 기준)

- **task1-print-plate**: 프로토타입(정합+픽셀diff) → 웹앱(`webapp/`)으로 발전, OCR 결합(Initiative A) + 신뢰도 분류기(Initiative B)까지 구현·검증 완료.
- **task2-die-blade**: 데모/QA 리포트 완료, 이후 진행 없음.
- PDCA phase: `do` (task1-print-plate, phase 3)

---

## 한 일

### ① task1-print-plate 프로토타입 (`docs/dev/task1-print-plate/`)
- ORB+호모그래피 정합 → 픽셀 차분 → bbox 검출 → recall 평가 파이프라인 구축
- 합성 결함 생성기(오탈자/문자누락/점누락/성분표시오류/번짐) 완성
- QA 지적 3건(Otsu 임계값 불안정, 라인단위 GT 근사, Precision 지표 부재) 코드 수정 완료
  (robust threshold + 오검출 가드레일, 결함단위 GT, precision proxy)
- Gap 분석(2026-07-08): 프로토타입 선언 범위 기준 ~85%, 전체 설계 범위 기준 ~23%(의도된 범위 축소)

### ② task2-die-blade
- 데모(`die_blade_qc_demo.py`) + QA 리포트 완료

### ③ webapp — 실제 서비스화
- **backend**(FastAPI): `/api/health`, `/api/analyze`, `/api/results/{id}` 구현. task1 파이프라인 재사용(`pipeline_bridge.py`)
- **frontend**(Next.js): 업로드/결과뷰/어노테이션 이미지/히스토리 사이드바 컴포넌트 완성
- **Initiative A (OCR diff)**: `ocr_diff.py` — EasyOCR 라인 텍스트 diff, `pixel_diff`/`ocr_diff`/`both` provenance 병합 완료
- **Initiative B (신뢰도 분류기)**: `reliability.py` + `ml-training/` 파이프라인 완성
  - 데이터셋: 60쌍 이미지 × 240회 실행 → 1,242 rows (positive 255 / negative 987)
  - 모델(LogisticRegression) 학습 완료(2026-07-10 16:01): val_accuracy 98.1%, precision 91.4%, recall 100%
  - `ml/reliability_model.json`, `ml/reliability_meta.json` 커밋되어 백엔드에서 로드 확인

### ④ 2026-07-10 세션 — 서버 재기동 및 회귀 검증
- 백엔드(8000)/프론트엔드(3000) 재기동. 원인: bash 환경에서 `uvicorn`이 PATH에 없어 최초 시도 실패 → `python -m uvicorn`으로 해결. (기존 로그의 EADDRINUSE는 과거 기록, 실제 포트 충돌 없었음)
- `/api/analyze` 실사용 호출로 `source`/`reliability_score` 필드가 정상 채워짐을 확인
- **회귀 테스트 3종 통과** (`ML-ARCHITECTURE.md §6` 고정 acceptance gate 기준):

| 케이스 | 예전(픽셀diff 단독) | 지금(OCR+분류기 결합) | 판정 |
|---|---|---|---|
| 무결함(정합오차만, QA 발견1 원인 케이스) | 임계값 9 → 박스1개, 라벨 전체(93%) 오검출 | 박스 1개, area_ratio 1.1%, oversized=False, reliability_score=0.0005(노이즈로 정확히 분류) | ✅ 재발 없음 |
| 성분표시오류 단독(defective_04) | QA에서 반증됨 | 박스 6개 모두 area_ratio 0.2~1.2%, oversized 없음, 진짜 결함(both)만 reliability 0.95~0.98 | ✅ 통과 |
| 5결함 통합 데모(README) | Recall 80%(4/5), 점누락 미검출 | Recall 100%(5/5), reliable_recall 100%, critical_missed=False, any_oversized=False | ✅ 개선(점누락도 OCR로 검출) |

- 결론: 규칙 기반 가드레일(면적 20% 상한) + 신뢰도 분류기가 이중 방어선으로 작동. 회귀 없음, 일부 지표는 개선.

### ⑤ 2026-07-10~11 세션 — 프론트엔드 reliability/source 뱃지 구현 + 브라우저 검증
- `lib/api.ts` 타입에 누락돼 있던 `source`/`reliability_score`(DetectionItem), `ocr_text_before`/`ocr_text_after`(PerDefectItem) 추가 — 백엔드 스키마와 어긋나 있던 문제 해소
- `globals.css`에 `visual-design-system.md` §7.1 명시 토큰(`--source-ocr`, `--reliability-ok`/`--reliability-low`) 라이트/다크 모두 추가
- `DetectionList.tsx`: reliability 컬럼(초록 점+점수 / 앰버 "확인 필요" 뱃지 / null이면 미표시), source 뱃지(픽셀/OCR/둘 다), 결함별 OCR diff 컬럼(before→after) 구현
- Playwright(헤드리스 Chromium, npx 캐시 경유)로 실제 업로드→분석→결과 화면까지 구동해 뱃지 렌더링과 콘솔 에러 없음을 스크린샷으로 확인 — **완료**

### ⑥ 2026-07-11 — 설명용 만화 2종 제작
- **프로세스 만화**(정합→픽셀diff/OCR→병합→신뢰도분류→리포트, CMYK 분판 메타포): https://claude.ai/code/artifact/42a5f1cd-d335-4529-a96e-949c0119f283
- **아키텍처 만화**(webapp/ARCHITECTURE.md를 인쇄소 도면 방+배관 구조로 표현): https://claude.ai/code/artifact/5f1555a4-de6c-4dbe-874f-c9aedb3f96d1
- 둘 다 라이트/다크 테마 Playwright 렌더링 검증 완료(다크모드 벤다이어그램 블렌드모드 버그, JSX 중괄호 이스케이프 버그 각 1건 발견 후 수정)

---

## 해야할 일 (남은 작업)

1. **Gap 분석(2026-07-08) 잔여 항목**
   - G4: 원본↔버전 검증 게이트 미구현 (오검출 주원인 미차단)
   - G5: 실제 인쇄물/스캔 이미지로 파라미터 재튜닝 (현재 전부 합성 이미지 기준)
   - G6~G8: 검사자 UI의 HITL 강제 라우팅, MES 연계 미구현
2. **이식성 부채**: `generate_labels.py`의 `C:/Windows/Fonts/malgun.ttf` 절대경로 하드코딩 → 비Windows 환경 실행 불가
3. 신뢰도 분류기 decision_threshold(현재 0.5 고정) 실사용 데이터 기반 재보정 여부 검토

---

## 실행 중인 프로세스 (2026-07-10 세션)
- Backend: `python -m uvicorn main:app --reload --port 8000` (background, log: `webapp/backend/backend4.log`)
- Frontend: `npm run dev` (background, log: `webapp/frontend/frontend2.log`)
