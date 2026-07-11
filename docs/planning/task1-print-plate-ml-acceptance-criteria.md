# 이번 세션 완료 기준 (Definition of Done) — 과제① 인쇄판 ML 확장

> 근거: `docs/planning/task1-print-plate-ml-plan.md` §7 Open Questions(미확답) + `webapp/ML-ARCHITECTURE.md`(아키텍트 확정 스펙).
> 사용자가 부재중이라 §7의 3개 질문에 팀 가정을 명시적으로 적용한다. "가정:"으로 표시된 항목은 확정된 사용자 결정이 아니며, 사용자 복귀 시 재확인 필요.

## 0. Open Questions에 대한 팀 가정

| # | 질문 | 가정 | 근거 |
|---|---|---|---|
| 1 | 실사 촬영 이미지 확보 시점 | 가정: 이번 패스에서는 실사 이미지가 **없다**고 가정한다. 로드맵 3주차(실사 OCR 검증)와 4.3 Phase B(실사 피드백)는 이번 패스 범위에서 제외하고, "확보되는 대로 착수" 조건부 후속 작업으로 문서에만 명시한다. | 사용자 미확답 상태에서 실사 검증을 블로커로 두면 이니셔티브 A/B 전체가 멈춘다. 합성 데이터만으로 진행 가능한 범위가 이미 로드맵 1~2, 3~5주차에 존재. |
| 2 | "맞음/틀림" 피드백 UI 포함 여부 | 가정: 이번 패스에서는 **제외**한다. 백엔드 스키마(`source`, `reliability_score`, `ocr_text_*`)와 오프라인 학습 파이프라인까지가 4명(아키텍트/데이터분석/개발/디자이너)이 현재 소화 가능한 범위이며, 피드백 UI+`/api/history` 확장은 로드맵 7주차 항목으로 별개의 스프린트다. | ML-ARCHITECTURE.md는 피드백 루프(Phase B)를 학습 데이터 확보 "2단계" 중 실사 단계로만 언급하며, 이번 스펙(§1~§6)에 피드백 UI 관련 API/컴포넌트가 전혀 없다 — 즉 아키텍트도 이번 스코프에서 이미 제외한 상태. |
| 3 | 클라우드 OCR 예산 승인 | 가정: 승인받지 않은 것으로 간주하고 **로컬 OCR(EasyOCR)만 사용**한다. | 계획 §2·§3(A-03)이 이미 "로컬/오프라인 우선"을 명시했고, ML-ARCHITECTURE.md §1도 `easyocr`만 런타임 의존성으로 확정했다 — 클라우드 API 코드/설정은 이번 패스에 아예 작성하지 않는다. |

## 1. 이니셔티브 A — OCR 결합: 이번 패스 DoD

**포함 (in scope)**
- [ ] `webapp/backend/ocr_diff.py` 구현: `detect_text_diffs()`가 ML-ARCHITECTURE.md §3 step 3 시그니처대로 `(ocr_boxes, ocr_lines)` 반환, EasyOCR 실패/미설치 시 예외 없이 `([], [])` 반환
- [ ] `merge_with_source()` 구현: pixel_boxes + ocr_boxes → `(x,y,w,h,area,source)` 병합, source 규칙(§3 merge semantics) 정확히 구현
- [ ] `pipeline_bridge.analyze()`에 OCR 분기 + 병합 + area_ratio/oversized 재계산 통합 (ML-ARCHITECTURE.md §3의 9단계 순서 그대로)
- [ ] `schemas.py`에 `DetectionItem.source`, `PerDefect.ocr_text_before/after` 필드 추가, 기본값/degradation 규칙(§2) 준수
- [ ] **회귀 게이트(하드 바)**: README 합성 데모 5개 결함 케이스에서 **5/5 검출** (기존 4/5, 점누락 포함) — 계획 G-01 KPI 그대로, 낮추지 않음
- [ ] EasyOCR 없이 실행해도 `AnalyzeResponse`가 유효(모든 `source="pixel_diff"`, `ocr_text_*=null`) — 기존 동작과 100% 동일한 결과

**제외 (out of scope, 후속 패스로 명시 이월)**
- 실사/스캔 이미지로의 OCR 정확도 별도 검증 (로드맵 3주차) — 가정 #1에 따라 실사 이미지 미확보로 이번 패스 불가
- 클라우드 OCR 검토/전환 — 가정 #3에 따라 로컬 OCR로 충분한지와 무관하게 이번 패스에서 코드화하지 않음

## 2. 이니셔티브 B — 오검출 판별기: 이번 패스 DoD

**포함 (in scope)**
- [ ] `webapp/backend/reliability.py`: `FEATURE_NAMES`(8개, ML-ARCHITECTURE.md §5 순서 고정), `extract_features()`, `score_boxes()` 구현
- [ ] `ml-training/generate_dataset.py`: `generate_labels.py` 확장, 합성 부트스트랩으로 `reliability_dataset.csv` 생성 (§4 스키마·헤더 순서 정확히), `dataset_manifest.json` 동반 생성
- [ ] `ml-training/train_reliability.py`: StandardScaler + LogisticRegression 학습 → `backend/ml/reliability_model.json` + `reliability_meta.json` 내보내기 (§4 포맷)
- [ ] `reliability.py` 로드 시 `feature_names`/`schema_version` 불일치 검증 → 불일치 시 예외 없이 스코어링 비활성화(`None`)
- [ ] `schemas.py`에 `DetectionItem.reliability_score: Optional[float]` 추가
- [ ] **회귀 게이트(하드 바)**: QA [발견 1] 재현 케이스(성분표시오류 단독 발생) — 분류기가 해당 박스를 `unreliable`로 정확히 분류 — 계획 G-02 KPI 그대로
- [ ] 기존 `oversized` 규칙 기반 가드레일은 완전히 유지 (이중 방어, 대체 아님)
- [ ] 모델 아티팩트가 없거나 로드 실패 시 `reliability_score=null`로 정상 응답 (예외 없음)

**제외 (out of scope, 후속 패스로 명시 이월)**
- 실사 피드백 UI("맞음/틀림" 버튼) 및 `GET/POST /api/history` 확장 — 가정 #2에 따라 이번 패스 제외 (로드맵 7주차)
- 실사 피드백 데이터 기반 재학습 — Phase B 전체가 실사 이미지 부재(가정 #1)로 후속
- LightGBM/CNN 스트레치 목표 — 계획 §4.4에 명시된 이후 단계, 이번 패스는 LogisticRegression만

## 3. 프론트엔드/디자이너 이번 패스 DoD
- [ ] `visual-design-system.md`에 `reliability_score < 0.5` → amber "확인 필요" 배지, `null` → 배지 없음, `oversized`는 별도 병기 — 명세만 이번 패스 대상 (실제 컴포넌트 구현은 개발자 스코프 확인 필요, 배지 API 계약은 확정)
- [ ] 피드백 버튼 UI는 그리지 않음 (가정 #2)

## 4. 통합 회귀 세트 (모든 변경 후 필수 재실행)
1. README 5-결함 합성 데모 — 5/5 검출
2. QA [발견 1] 성분표시오류 단독 케이스 — `unreliable` 정확 분류
3. OCR/분류기 모두 부재 상태로도 기존 `AnalyzeResponse`와 동일한 결과 (하위호환)

## 5. 이번 패스 종료 조건
위 §1·§2 "포함" 체크박스 전부 완료 + §4 회귀 세트 3건 모두 통과 시 "이번 패스 완료"로 간주. §7 Open Questions 가정은 사용자 복귀 시 재확인 대상으로 남긴다.
