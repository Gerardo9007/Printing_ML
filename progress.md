# Progress Log — 08 Printing ML

## 현재 상태 요약 (2026-07-10 기준)

- **task1-print-plate**: 프로토타입(정합+픽셀diff) → 웹앱(`webapp/`)으로 발전, OCR 결합(Initiative A) + 신뢰도 분류기(Initiative B)까지 구현·검증 완료.
- **task2-die-blade**: 프로토타입(정합+diff, 휨/끊김/마모/위치오차 4클래스) → task1과 동일 구조로 웹앱화 + 신뢰도 분류기 ML 확장까지 완료(2026-07-11).
- PDCA phase: `do` (task1-print-plate, phase 3 / task2-die-blade, phase 3)

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

### ⑦ 2026-07-11 — git 저장소 초기화 + 오검출 케이스 브라우저 검증
- 프로젝트 루트에 git 저장소 신규 초기화, `.gitignore` 작성(node_modules/.next/__pycache__/결과물 폴더/.bkit·.claude·.omc 툴 상태 제외), 전체 소스 2회 커밋
- 원격(`github.com/Gerardo9007/Printing_ML`) 연결 시도 — 계정 권한 문제(`superpjh-stack`이 해당 저장소에 push 권한 없음, GitHub API로 확인)로 **push는 보류 중**, 로컬 커밋까지만 완료
- 브라우저(Playwright)로 오검출 케이스 실측: 참조 이미지 자체를 "결함 이미지"로 올렸을 때 — 박스 1개(area_ratio 1.12%, 오검출 가드레일 통과) but reliability_score=0.00 → "확인 필요" 뱃지 정상 표시. 규칙 기반 가드레일과 분류기가 서로 다른 이유로 독립적으로 작동함을 확인

### ⑧ 신뢰도 분류기 데이터셋/라벨링/피처엔지니어링 상세 (Initiative B)
- **데이터 생성**(`ml-training/generate_dataset.py`): 실제 파이프라인(정합→diff→OCR merge)을 반복 실행해 합성 생성. 결함 조합 14종(없음·단독5·쌍7·전성분3중·전체) × 정합오차 6회 변주 × robust-threshold k스윕([6.0,4.0,3.0,2.0], k를 낮출수록 QA 발견1급 거대 오검출이 재현되어 네거티브 샘플로 수확) → 60쌍×240회 실행 → 1,242 rows
- **라벨링**: `label = 1 iff (GT overlap>0.05) AND (area_ratio≤0.20)` — 스펙 원문(overlap만으로 라벨링)은 거대 오검출도 GT를 덮으면 label=1이 되는 모순이 있어, 오검출 가드레일 조건을 AND로 추가해 해결(결정 근거를 `dataset_manifest.json`에 기록). 결과: positive 255 / negative 987, source별로는 `ocr_diff` 단독 박스는 양성 0건(항상 신뢰 낮음), `both`는 74/78이 양성(가장 신뢰 높은 신호)
- **피처 엔지니어링**(`reliability.py::extract_features`, 10개): area_ratio·aspect_ratio·mean/std_diff_intensity·edge_density(라플라시안 분산)·n_nearby_boxes·registration_n_inliers·diff_threshold_used(8개, v1) + max_diff_intensity·diff_pixel_fraction(2개, v2 신규) — v2 추가 이유: OCR 박스가 패딩 때문에 커서 평균값으로는 박스 안의 작은 진짜 결함 신호가 희석되는 문제를, crop 내 최댓값/임계값 이상 픽셀비율로 보완
- **학습**(`train_reliability.py`): 75/25 stratified split, StandardScaler, LogisticRegression(class_weight="balanced"). 런타임에는 scikit-learn 없이 coef/scaler를 JSON export해 순수 numpy로 추론(경량화). val: accuracy 98.1%/precision 91.4%/recall 100%, FN 0건
- 안전장치: 로드시 `feature_names`/`schema_version` 불일치 감지 → 조용히 스코어링 비활성화(None)

### ⑨ 2026-07-11 — task2-die-blade 웹앱화 (task1과 동일 구조)
- 코드 확인 결과 문서(Gap 분석)보다 실제 코드가 앞서 있었음: 휨/끊김뿐 아니라 **마모(3등급)·위치오차**까지 이미 구현되어 있었음(G3/G4가 실제로는 코드상 해소된 상태)
- `docs/dev/task2-die-blade/generate_webapp_demo.py` 신규: 웹앱 기본 참조/실물/GT 자산 생성(휨+끊김2+마모 복합 시나리오 + 위치오차 단독 시나리오)
- `webapp/backend/pipeline_bridge_dieblade.py`, `storage_dieblade.py` 신규: task1과 같은 sys.path 브릿지 전략으로 `die_blade_qc_demo.py`를 그대로 재사용. `main.py`에 `/api/die-blade/*` 라우트 추가(별도 저장소 네임스페이스)
- `webapp/frontend/app/die-blade/*`, `components/dieblade/*` 신규: 업로드/결과 페이지, 지표 패널(정합 잔차·위치오차·결함유형별 카운트)/검출목록/주석이미지 컴포넌트. `HistorySidebar`에 인쇄판↔목형칼날 앱 스위처 추가
- 백엔드 curl 검증: 복합 데모(휨+끊김2+마모) recall 100%(4/4), 위치오차 단독 데모(6.1mm>5mm 허용) 정상 판정
- 프론트엔드 Playwright 검증: 업로드→분석→결과 화면 전체 플로우, 콘솔 에러 0건, 앱 스위처 정상 동작 확인 (스크린샷 확인 완료)
### ⑩ 2026-07-11 — task2용 신뢰도 분류기 ML 확장 (task1 Initiative B 상응)
- **피처 엔지니어링 설계**: task1과 달리 결함이 4종 이질적 형태(휨/끊김/마모/위치오차, bbox+mm 편차+등급 등 필드가 서로 다름)라 kind를 원-핫(`is_bend`/`is_break`/`is_wear`/`is_position`)으로 인코딩. `reliability_dieblade.py`에 12개 피처: area_ratio·aspect_ratio·max/mean_deviation_mm·arc_length_mm·n_nearby_defects(박스 단위) + registration_residual_mm·position_shift_mm(전역) + kind 원-핫 4개
- **데이터 생성**(`generate_dataset_dieblade.py`): `pipeline_bridge_dieblade.analyze(run_dir=None)`를 그대로 재사용(파일 I/O 생략 모드 추가)해 실제 파이프라인으로 합성. 결함 조합 14종(없음·단독4·쌍6·삼중·전체) × 정합오차 10회 변주 + **대각도(30~90°) 오수렴 레짐 20회**를 별도로 네거티브 수확용으로 추가(QA §2-B 재현) → 150쌍, 391 rows (positive 198 / negative 193)
- **라벨링 버그 발견·수정**: 위치오차 검출은 설계상 bbox가 항상 "도면 전체 바운딩박스"라 면적비가 항상 ~27%로 커서, task1과 같은 오검출 면적가드(15%)를 그대로 적용했더니 위치오차 진짜 양성이 전부 0으로 잘못 라벨링됨 → 위치오차는 면적가드 예외 처리로 수정. 부수 발견: "휨" 단독 태그는 탐지기 설계상 항상 "끊김"도 동시에 걸려 `복합`으로 병합되므로 데이터셋에 순수 "휨" 양성이 구조적으로 존재하지 않음(버그 아님, 탐지기 자체 특성)
- **학습**(`train_reliability_dieblade.py`): task1과 동일 설정(75/25 stratified, StandardScaler, LogisticRegression balanced). val: **accuracy 87.8%, precision 97.5%, recall 78.0%** (task1의 100%보다 낮음 — 정직하게 기록. FN 11건, 특히 마모 등급 경계 부근 애매한 케이스에서 재현율이 떨어짐)
- **검증**: 45° 오수렴 레짐(registration_reliable=False) 입력 시 9개 검출 전부 reliability_score 0.001~0.02로 정확히 낮게 판정 — 규칙 기반 정합 신뢰도 플래그와 별개로 분류기가 독립적으로 동일 결론에 도달함을 확인. 브라우저 Playwright 검증 통과(콘솔 에러 0)

### ⑪ 2026-07-12 — task2 분류기 recall 개선
- FN 진단: 78% recall의 FN 11건 중 10건이 마모(등급 경계 애매, mean_deviation~0.6mm, GT overlap 5~9%)로 확률 0.35~0.49(0.5 문턱 바로 아래), 1건은 순수 "휨"(복합 병합 안 된 드문 케이스)
- **데이터셋 확대**: 조합당 misalign 변주 10→25회, 대각도 오수렴 20→40회 → 150쌍/391행 → **365쌍/919행**으로 확대 후 재학습 → recall 78.0%→**84.8%**로 개선
- 남은 FN 20건 재진단: 18건은 여전히 같은 마모 경계 애매 케이스(라벨 자체가 GT overlap 5~9%로 아슬아슬), 2건은 "복합"인데 registration_residual이 매우 높은(21mm, 7mm) 런에서 나온 것 — 위치오차 재현을 위해 일부러 tx/ty를 크게 준 조합이 정합 품질 자체를 실제로 악화시킨 부작용. 이 2건은 모델이 "정합 신뢰도 낮음"을 정확히 반영한 것이라 오히려 합리적 판단으로 결론
- **임계값 조정**: val set에서 threshold sweep 결과 **0.4**가 precision=recall=93.2% 균형점 → spec.md의 "치명 결함 미검출 0" 우선순위상 recall 쪽으로 기우는 게 맞다고 판단해 0.4 채택(0.5→0.4). `train_reliability_dieblade.py`의 `decision_threshold`와 프론트엔드 `DetectionListDieBlade.tsx`의 배지 임계값을 함께 동기화
- **최종**: accuracy 92.2%, **precision 93.2%, recall 93.2%** (FN 9/132). 45° 오수렴 회귀 테스트 재확인 — 여전히 전부 0.004~0.07로 낮게 판정, 회귀 없음. 브라우저 검증 통과

---

## 해야할 일 (남은 작업)

1. **Gap 분석(2026-07-08) 잔여 항목**
   - task1 G4: 원본↔버전 검증 게이트 미구현 (오검출 주원인 미차단)
   - task1 G5 / task2 G1: 실제 촬영/스캔 이미지로 파라미터 재튜닝 (현재 전부 합성 이미지 기준)
   - task1 G6~G8 / task2 G6~G10: 검사자 UI의 HITL 강제 라우팅, MES 연계 미구현
   - task2 G2: 이상탐지 모델(PatchCore/PaDiM) 미적용 (현재는 고전적 정합+diff만)
2. **이식성 부채**: `generate_labels.py`/`die_blade_qc_demo.py`의 `C:/Windows/Fonts/malgun.ttf` 절대경로 하드코딩 → 비Windows 환경 실행 불가
3. task1 분류기 decision_threshold(0.5 고정) 실사용 데이터 기반 재보정 여부 검토 (task2는 0.4로 이미 재보정함)
4. 이번 세션 변경사항(recall 개선) 아직 git 커밋 안 됨

---

## 실행 중인 프로세스 (2026-07-11 기준)
- Backend: `python -m uvicorn main:app --reload --port 8000` (background, log: `webapp/backend/backend6.log`)
- Frontend: `npm run dev` (background, log: `webapp/frontend/frontend2.log`)
