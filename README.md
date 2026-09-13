# Pokemon GO Kakao Bot

카카오톡 메신저봇 API2, Railway FastAPI, PostgreSQL을 연결해 Pokemon GO 일정을 답하는 봇입니다. 동일 이벤트는 중복 저장하지 않고 갱신하며, 필요하면 환경 변수만 바꿔 Groq 또는 OpenAI 수집기로 전환할 수 있습니다.

## 일정 소스

1순위는 **공식 한국 사이트**(`pokemongo.com/ko/news`)입니다. 기사 본문에 `한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지` 형태로 KST 일정이 적혀 있고, 주간 릴레이 시간제한 리서치 같은 **한국 한정 이벤트**도 이곳에만 실립니다. 제목은 공식 한글 표기를 그대로 씁니다.

다만 공식 한국 사이트는 **레이드아워(매주 수 18:00), 스포트라이트아워(매주 목 18:00), 맥스먼데이, 주간 레이드 보스·GO배틀리그 로테이션, 요일별 보너스(쇼케이스 투스데이, 우정 프라이데이 등)**를 게시하지 않습니다. 이 부분은 한국 커뮤니티 사이트 **포케토리**(`poketory.com`의 매주 갱신되는 "이번 주의 이벤트 및 보너스 일정" 글)와 **포고지지**(`pgsharp-info.com`의 "일정" 게시판)가 보완합니다. 두 사이트 모두 한국시간 기준으로 이미 한글로 정리돼 있어 별도 번역이 필요 없습니다. 커뮤니티 소스 수집이 실패해도 공식 일정 수집은 계속됩니다.

각 이벤트에는 `region`이 붙습니다. 한국에서 참여 가능하면 `kr`, 해외에서만 열리는 현장·티켓 이벤트는 `overseas`이며, 카카오톡 답장에서 해외 전용 일정은 🌏 표시와 함께 한국 일정 **아래에 따로 묶여** 나옵니다.

## 지원 명령어

- `포고봇 오늘`, `포고봇 내일`, `포고봇 이번주`
- `포고봇 레이드`, `포고봇 레이드아워`
- `포고봇 스포트라이트`, `포고봇 커뮤`
- `포고봇 다음 이벤트`, `포고봇 지금 뭐해`
- `포고봇 리스트`, `포고봇 도움말`, `포고봇 테스트`

## Railway 환경 변수

기존 `DATABASE_URL`에 다음 값을 추가합니다.

- `AI_PROVIDER`: 기본값 `gemini`
- `GEMINI_API_KEY`: Google AI Studio에서 발급한 API 키
- `GEMINI_MODEL`: 기본값 `gemini-3.6-flash`
- `ADMIN_TOKEN`: 관리자 API에 사용할 충분히 긴 임의 문자열

실제 값은 저장소에 커밋하지 마세요. `.env.example`은 이름과 형식만 보여주는 예시입니다.

Groq로 전환하려면 `AI_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL`을 설정합니다. OpenAI로 전환하려면 `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`을 설정합니다. NVIDIA(NIM)로 전환하려면 `AI_PROVIDER=nvidia`, `NVIDIA_API_KEY`, 필요하면 `NVIDIA_MODEL`(기본값 `google/gemma-4-31b-it`)을 설정합니다. reasoning이 기본으로 켜진 모델(Nemotron 계열 등)은 내부적으로 "생각" 단계를 거치느라 이 수집기가 넘기는 큰 입력(수만 자)에서 응답이 매우 느려질 수 있어, reasoning이 기본 꺼짐인 모델을 기본값으로 씁니다. NVIDIA NIM 모델은 종종 서비스 종료(EOL)되니, 수집이 `410`/`model ... no longer available` 오류로 실패하면 [build.nvidia.com](https://build.nvidia.com/models)에서 현재 제공 중인 모델 ID로 `NVIDIA_MODEL`을 갱신하세요. 응답이 120초를 넘기면 (재시도 없이) 타임아웃으로 실패합니다(`APITimeoutError`). NVIDIA NIM은 자체 웹 검색 기능이 없어서, Gemini와 마찬가지로 봇이 직접 가져온 공식 한국 뉴스 + 한국 커뮤니티 소스 텍스트를 구조화하는 방식으로 동작합니다. 선택하지 않은 공급자의 API 키는 필요하지 않습니다.

## 배포 후 최초 수집

Swagger `/docs`에서 `POST /api/admin/collect?days=30`을 실행하고 요청 헤더 `x-admin-token`에 Railway의 `ADMIN_TOKEN` 값을 넣습니다. 응답의 `found`, `inserted`, `updated`로 결과를 확인합니다.

기존 `events` 테이블은 삭제하지 않습니다. 앱 시작 시 필요한 열과 `collect_runs` 테이블이 자동으로 추가됩니다. 새 데이터는 출처 URL, 분류, 시작 시각을 해시한 `external_key`로 upsert됩니다 (제목은 소스가 바뀌어도 같은 이벤트로 인식되도록 키에서 제외).

## 이벤트 삭제

세 관리자 API 모두 `POST /api/admin/collect`와 같은 방식으로 `x-admin-token` 헤더가 필요합니다.

- `DELETE /api/admin/events/{event_id}`: 이벤트 하나를 id로 삭제합니다. 없는 id면 404를 반환합니다.
- `DELETE /api/admin/events/dedupe`: 출처 URL·분류·시작/종료 시각이 같은 중복 이벤트 중 오래된 행(가장 낮은 id)만 지우고 최신 행은 남깁니다. 예전 `external_key` 산출 방식이 title을 포함하던 시절 생긴 레거시 중복(같은 이벤트가 영문/한글로 각각 저장된 경우 등)을 정리할 때 씁니다. 응답의 `removed`로 삭제된 개수를 확인합니다.

## 자동 수집

웹 서비스가 실행 중이면 같은 프로세스에서 한국 시간 06:00과 18:00에 자동으로 30일 일정을 수집합니다. 별도 Railway Cron 서비스는 필요하지 않습니다. 끄려면 `AUTO_COLLECT_ENABLED=false`를 설정합니다. 서비스는 하나의 replica로 실행하는 것을 권장합니다.

앱 시작 시 예전에 생성된 `source_name=TEST` 테스트 일정은 자동으로 정리되며, 테스트 일정 생성용 관리자 API는 제공하지 않습니다.

## 로컬 실행과 테스트

```bash
python -m pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload
```

`DATABASE_URL`이 없으면 로컬 SQLite 파일을 사용합니다. 기본 설정으로 실제 일정을 수집하려면 `GEMINI_API_KEY`가 필요합니다.
