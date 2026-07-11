# 기획 문서 — 과제① 인쇄판 문안검사: ML 도입 (OCR 결합 + 오검출 판별기)

> 근거 문서: `docs/dev/task1-print-plate/README.md`(실측 결과·구조적 한계), `docs/qa/task1-print-plate-qa-report.md`(발견 1·2), `webapp/ARCHITECTURE.md`, `OCR 결합 방안.docx`, `인쇄판 문안검사 ML 방안.docx`. 본 문서는 위 문서들과 상충되는 내용을 임의로 정하지 않으며, 미해결 사항은 "가정:"으로 명시한다.

## 0. 현재 상태 요약 (근거: README, QA 리포트)

- 현재 파이프라인은 **ML을 전혀 쓰지 않는** 순수 CV/규칙 기반이다 (ORB+호모그래피 정합, 픽셀 diff+robust threshold).
- 실측 Recall 80% (5건 중 4건), 점누락(마침표)만 구조적으로 미검출 — 픽셀 diff로는 원천적으로 어려운 케이스로 README가 이미 확인함.
- QA [발견 1]: 성분표시오류가 **단독으로** 발생하면 같은 코드가 라벨 전체(93% 면적)를 오검출 박스로 반환 — 현재는 `oversize_area_ratio=0.20` 고정 임계값 가드레일로만 방어 중이며, 근본적으로는 "규칙 하나로 모든 결함 조합·촬영조건을 커버할 수 없다"는 구조적 취약점이 남아 있음.
- 이번 기획은 이 두 가지 이미 식별된 지점을 각각 정식 ML 이니셔티브로 승격하는 것이다.

---

## 1. 목표 (Goal)

| ID | 목표 | 성공 기준 (KPI) | 근거 |
|---|---|---|---|
| G-01 | OCR 결합으로 문자 단위 결함 재현율을 100%로 끌어올린다 | 합성 데모 5/5 결함 검출 (현재 4/5, 점누락 포함) | README "중요한 발견" |
| G-02 | 오검출 판별기로 "라벨 전체를 뒤덮는 오검출" 재발을 구조적으로 차단한다 | 성분표시오류 단독 발생 케이스에서 판별기가 해당 박스를 unreliable로 정확히 분류 | QA [발견 1] |
| G-03 | 두 이니셔티브 모두 로컬 데모 철학(무인증·무DB·오프라인 우선) 유지 | 신규 외부 API/클라우드 의존 없이 1차 구현 완료 | webapp/ARCHITECTURE.md 방향성 |

---

## 2. 두 이니셔티브 비교 및 우선순위

| 항목 | OCR 결합 | 오검출 판별기 |
|---|---|---|
| 해결하는 문제 | 미세 텍스트 결함 미검출 (Recall) | 오검출 폭증 리스크 (신뢰성/Precision) |
| ML 유형 | **사전학습** OCR 모델(전이학습) + 규칙 기반 문자열 diff | **직접 학습**이 필요한 지도학습 이진분류 |
| 학습 데이터 필요량 | 없음 (사전학습 모델 그대로 사용, 검증용 샘플만 필요) | 있어야 함 (합성으로 부트스트랩 가능) |
| 구현 난이도 | 낮음 (라이브러리 통합 수준) | 중간 (피처 설계 + 학습·평가 루프 필요) |
| **우선순위** | **P0 (1순위)** | **P1 (2순위)** |

**우선순위 근거**: OCR은 데이터 수집 없이 즉시 착수 가능한 빠른 개선이다. 오검출 판별기는 학습 데이터가 필요한데, OCR 결합 이후 diff 후보 박스의 종류(pixel_diff/ocr_diff)가 다양해진 상태에서 학습 데이터를 모으는 것이 더 견고한 분류기를 만든다 — 따라서 OCR을 먼저 통합한다.

---

## 3. 이니셔티브 A — OCR 결합 (요약; 세부 설계는 `OCR 결합 방안.docx` 참조)

| ID | 항목 | 내용 |
|---|---|---|
| A-01 | 파이프라인 위치 | `registration` 이후, `diff_detect`와 병렬 분기 → 결과를 `merge_close_boxes`로 병합 |
| A-02 | 비교 단위 | 줄(line) 단위 OCR → `difflib.SequenceMatcher` 문자열 diff → 인덱스 구간을 픽셀 bbox로 환산 |
| A-03 | 엔진 후보 | EasyOCR / PaddleOCR (순수 pip, 오프라인) — 클라우드 OCR은 실사 정확도 부족 시에만 재검토 |
| A-04 | 오검출 억제 | NFKC 정규화 + `SequenceMatcher.ratio()` 임계값(예: 0.97)으로 OCR 노이즈 흡수 |
| A-05 | 스키마 변경 | `detections[].source: "pixel_diff"\|"ocr_diff"\|"both"`, `per_defect[].ocr_text_before/after` 추가 |

---

## 4. 이니셔티브 B — 오검출 판별기 (ML 설계 상세)

### 4.1 문제 정의
- **입력**: `diff_detect.compute_diff_mask`가 반환한 박스 1개 + 그 박스의 특징
- **출력**: 이진분류 — `reliable`(1, 실제 결함) vs `unreliable`(0, 정합잔차 노이즈/오검출)
- 기존 `oversized: bool`(고정 면적비 규칙)을 **대체하지 않고 이중 방어**로 유지한다 — 분류기가 실패해도 규칙 기반 가드레일이 최후 방어선 역할을 하도록.

### 4.2 피처 설계 (박스 단위)

| 피처 | 설명 |
|---|---|
| `area_ratio` | 박스 면적 / 전체 이미지 면적 (기존 `diff_detect` 출력 재사용) |
| `aspect_ratio` | w/h — 라벨 전체를 덮는 오검출은 보통 큰 정사각/가로형 |
| `mean_diff_intensity`, `std_diff_intensity` | 박스 내부 diff 강도 통계 — 노이즈는 낮고 균일, 실결함은 국소적으로 강함 |
| `edge_density` (Laplacian variance) | 텍스트 결함 특유의 에지 패턴 유무 |
| `n_nearby_boxes` | `merge_close_boxes` 병합 이력 — 병합이 많을수록 QA [발견 1] 패턴과 유사 |
| `registration_n_inliers` | 전역 피처 — 정합이 불안정할수록 노이즈성 오검출 확률 상승 |
| `diff_threshold_used` | 전역 피처 — robust threshold 값 자체가 낮게 잡힌 상황(QA 발견 1의 근본 원인)을 신호로 활용 |

### 4.3 학습 데이터 확보 (2단계)

| 단계 | 방법 | 산출 |
|---|---|---|
| Phase A (부트스트랩) | `generate_labels.py` 확장 → 결함 조합·정합오차 강도를 다양화한 합성 이미지 수백~수천 장 자동 생성. GT와 겹치면 1, 안 겹치면(=QA 발견1류 노이즈) 0을 **자동** 라벨링 | 초기 학습셋 (사람 라벨링 불필요) |
| Phase B (실사 피드백) | 웹서비스 `DetectionList`에 "맞음/틀림" 피드백 버튼 추가 → `GET/POST /api/history` 확장해 사람 피드백 누적 | 실사 기반 재학습 데이터 (지속 누적) |

### 4.4 모델 선택
- 1차: **Logistic Regression** 또는 소형 **Gradient Boosting**(LightGBM 등) — 해석 가능, 적은 데이터로도 동작, 프로젝트의 "경량 의존성" 철학과 부합.
- 스트레치 목표(데이터 충분해진 뒤): diff 영역 crop을 입력으로 하는 소형 CNN patch classifier.

### 4.5 통합 지점 및 API 영향
- `diff_detect` 출력 후 → `classifier.predict_proba(box_features)` → `reliability_score: float` 필드를 `detections[]`에 추가.
- 프론트엔드 `visual-design-system.md`의 배지 체계에 자연스럽게 얹음 (예: `reliability_score < 0.5`이면 amber "확인 필요" 배지, 기존 `oversized` 배지와 별도 병기).

### 4.6 평가 지표
- QA [발견 1] 재현 케이스(성분표시오류 단독)에서 분류기가 해당 박스를 `unreliable`로 정확히 판정하는지 (회귀 테스트로 고정)
- `precision_proxy` 개선폭 (현재 62.1%, 회귀 데모 기준)
- False positive rate 감소 (다양한 합성 변형 테스트셋 기준)

---

## 5. 통합 로드맵

| 주차 | 이니셔티브 | 내용 |
|---|---|---|
| 1주 | A (OCR) | EasyOCR/PaddleOCR PoC — 합성 데모 줄 영역 텍스트 추출 정확도 확인 |
| 2주 | A (OCR) | `ocr_diff.py` 구현 + `merge_close_boxes` 병합 → 5/5 재현율 회귀 테스트 |
| 3주 | A (OCR) | 실제 촬영/스캔 라벨 샘플로 OCR 정확도 별도 검증 |
| 3~4주 | B (판별기) | `generate_labels.py` 확장 → 합성 부트스트랩 학습셋 생성 (OCR 통합 이후라 pixel_diff+ocr_diff 박스가 함께 섞여 더 견고) |
| 5주 | B (판별기) | 피처 추출 + Logistic Regression/LightGBM 학습 + QA 발견1 회귀 테스트로 평가 |
| 6주 | A+B | `pipeline_bridge.py`/`POST /api/analyze` 응답에 `source`, `ocr_text_before/after`, `reliability_score` 반영 |
| 7주 | B | 웹서비스에 피드백 버튼(맞음/틀림) 추가 → `GET /api/history` 확장, 실사 피드백 루프 가동 |

---

## 6. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| OCR이 실사 촬영 조건(잉크 텍스처·조명·곡면)에서 정확도 하락 | Recall 개선 효과 무산 | 로컬 OCR 우선 검증(3주차), 부족 시 클라우드 OCR로 승격 검토 |
| 오검출 판별기 학습 데이터 부족(특히 실사) | 분류기가 합성 데이터에만 과적합 | 합성 부트스트랩 + 사용자 피드백 루프로 지속 보강 |
| `detections[]` 스키마가 두 이니셔티브에 걸쳐 두 번 바뀜 (`source`, `reliability_score`) | 프론트엔드 변경이 두 차례 필요 | 스키마를 5장(로드맵) 6주차에 한 번에 합쳐 반영 |
| 두 ML 이니셔티브 병행으로 QA 재현 범위 확대 | 회귀 테스트 부담 증가 | QA [발견 1]·README 데모 케이스를 고정 회귀 세트로 삼아 매 변경 후 필수 재실행 |

---

## 7. Open Questions (사용자 확인 필요)

- [ ] 실사 촬영 이미지를 언제·몇 장 확보할 수 있는가? (Phase 3, 4.3 Phase B 착수 시점 결정)
- [ ] 오검출 판별기용 "맞음/틀림" 피드백 UI를 이번 스프린트에 포함할지, 이후로 미룰지?
- [ ] OCR 클라우드 API(비용 발생) 사용을 예산/보안 관점에서 승인 가능한지, 아니면 로컬 OCR로 끝까지 갈지?
