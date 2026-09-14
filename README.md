# Pokemon GO Kakao Bot

카카오톡 메신저봇 API2, Railway FastAPI, PostgreSQL을 연결해 Pokemon GO 일정을 답하는 봇입니다. 동일 이벤트는 중복 저장하지 않고 갱신하며, 필요하면 환경 변수만 바꿔 Groq 또는 OpenAI 수집기로 전환할 수 있습니다.

## 일정 소스

1순위는 **공식 한국 사이트**(`pokemongo.com/ko/news`)입니다. 기사 본문에 `한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지` 형태로 KST 일정이 적혀 있고, 주간 릴레이 시간제한 리서치 같은 **한국 한정 이벤트**도 이곳에만 실립니다. 제목은 공식 한글 표기를 그대로 씁니다.

다만 공식 한국 사이트는 **레이드아워(매주 수 18:00), 스포트라이트아워(매주 목 18:00), 맥스먼데이, 주간 레이드 보스·GO배틀리그 로테이션, 요일별 보너스(쇼케이스 투스데이, 우정 프라이데이 등)**를 게시하지 않습니다. 이 부분은 한국 커뮤니티 사이트 **포케토리**(`poketory.com`의 매주 갱신되는 "이번 주의 이벤트 및 보너스 일정" 글)와 **포고지지**(`pgsharp-info.com`의 "일정" 게시판)가 보완합니다. 두 사이트 모두 한국시간 기준으로 이미 한글로 정리돼 있어 별도 번역이 필요 없습니다. 커뮤니티 소스 수집이 실패해도 공식 일정 수집은 계속됩니다.

각 이벤트에는 `region`이 붙습니다. 한국에서 참여 가능하면 `kr`, 해외에서만 열리는 현장·티켓 이벤트는 `overseas`이며, 카카오톡 답장에서 해외 전용 일정은 🌏 표시와 함께 한국 일정 **아래에 따로 묶여** 나옵니다.

## 지원 명령어

- `/포고봇 오늘`, `/포고봇 내일`, `/포고봇 이번주`
- `/포고봇 레이드`, `/포고봇 레이드아워`
- `/포고봇 스포트라이트`, `/포고봇 커뮤`
- `/포고봇 상성 [타입]` — 타입 상성표 (예: `/포고봇 상성 불꽃`)
- `/포고봇 다음 이벤트`, `/포고봇 지금 뭐해`
- `/포고봇 예약 09:00` (1회), `/포고봇 예약 매일 09:00` (정기), `/포고봇 예약확인`, `/포고봇 예약취소`
- `/포고봇 수집` — 카카오톡에서 바로 최신 이벤트 수집 실행
- `/포고봇 리스트`, `/포고봇 도움말`, `/포고봇 테스트`

## 채팅으로 수집 실행

`x-admin-token`으로 `/api/admin/collect`를 직접 호출하지 않아도, 방에서 `/포고봇 수집`을 보내면 바로 실행됩니다. 관리자 API와 달리 별도 인증은 없습니다. 두 단계로 동작합니다: `/api/messages`가 즉시 `🔄 이벤트 수집을 시작했어요...` 응답과 함께 `await_collect: true` 플래그를 주면, 폰 스크립트가 같은 흐름 안에서 바로 이어서 `POST /api/collect`를 긴 타임아웃(4분)으로 호출해 실제 수집이 끝날 때까지 기다린 뒤 결과를 두 번째 메시지로 보냅니다. 예전에는 백그라운드 스레드 + outbox 폴링으로 전달했는데, 그 폴링이 다른 채팅 메시지가 와야만 실행돼서 조용한 방에서는 결과가 영영 도착하지 않는 문제가 있어 이 방식으로 바꿨습니다. 이미 진행 중인 수집이 있으면 새로 시작하지 않고 "이미 진행 중" 안내만 돌려줍니다.

## 타입 상성표

`/포고봇 상성 [타입]`은 AI를 거치지 않고 `app/type_chart.py`에 하드코딩된 18타입 상성표(Pokemon GO 기준, 페어리 포함 6세대 이후 표준)를 즉시 조회해서 답합니다 - 공격 시 2배/0.5배/무효와, 그 타입의 약점·저항·면역을 함께 보여줍니다. 정적인 게임 데이터라 AI 호출 없이 즉답 가능합니다.

## 자유 질문 (AI 답변)

위 명령어에 없는 질문도 `/포고봇 ...`으로 물어보면 AI가 답합니다. 일정(이벤트 시작/종료, 보너스 등) 질문은 등록된 일정을 근거로 답하고, 그 외 일반 Pokemon GO 지식 질문(타입별 추천 포켓몬, 공략 등)은 AI 자체 지식으로 답합니다 - 다만 메타에 따라 바뀌는 내용(최고/추천 포켓몬 등)은 최신 정보와 다를 수 있다고 안내를 덧붙입니다. 수집용 `AI_PROVIDER` 설정과 무관하게 항상 NVIDIA 무료 티어(`NVIDIA_MODEL`, 기본값 `meta/llama-3.2-11b-vision-instruct`)를 씁니다 - 수집용 Gemini/기타 할당량을 안 쓰려는 목적입니다. 전달 방식은 `/포고봇 수집`과 동일하게 두 단계 블로킹 호출(`/api/messages` 즉시 응답 + `await_ask: true` → `POST /api/ask` 긴 타임아웃 호출)입니다.

## 예약 발송

방마다 `/포고봇 예약 09:00`(오늘/내일 1회) 또는 `/포고봇 예약 매일 09:00`(매일 정기)으로 그 방에 "/포고봇 오늘" 목록을 KST 기준 지정 시각에 자동 발송하도록 예약할 수 있습니다. 방당 예약은 하나이며, 다시 예약하면 이전 예약을 덮어씁니다. `/포고봇 예약확인`으로 상태 확인, `/포고봇 예약취소`로 취소합니다.

서버(FastAPI)는 카카오톡 방에 직접 메시지를 보낼 수 없고, 오직 메신저봇R 스크립트만 보낼 수 있습니다. 그래서 구조는 다음과 같습니다: 서버는 예약 시각이 된 항목을 `GET /api/subscriptions/due` 큐에 담아두고, `messenger-bot/pogo-bot.js`가 이 엔드포인트를 폴링해서 `bot.send(room, message)`로 각 방에 직접 전달합니다.

이 폴링은 채팅과 무관한 타이머가 아니라 **메시지 수신 이벤트에 얹혀서** 돕니다 - 사용 중인 메신저봇R 빌드에서는 `setInterval`도 `Event.TICK`도 실제로 발생하지 않는 것이 확인됐고(앱 UI에도 별도 예약/매크로 실행 메뉴가 없음), 유일하게 확실히 불리는 게 `Event.MESSAGE`뿐이라 아무 메시지나(/포고봇 접두사 없어도) 올 때마다 20초 디바운스로 큐를 확인합니다. **즉 봇이 있는 모든 방을 통틀어 한동안 메시지가 전혀 없으면 그동안은 예약 발송도 전달되지 않습니다** (방 하나라도 활동이 있으면 전체 큐가 같이 처리되어 조용한 방 것도 함께 배달됩니다).

메시지 수신은 `function response(room, msg, sender, isGroupChat, replier, ...)` 전역 훅이 아니라 `BotManager.getCurrentBot().addListener(Event.MESSAGE, function(msg) {...})` 이벤트 리스너로 등록해야 실제로 호출됩니다 - 사용 중인 메신저봇R 빌드에서 전역 훅 방식은 알림 권한·배터리 설정과 무관하게 아예 호출되지 않는 것이 확인됐습니다.

### 스크립트 배포 (원격, 폰 직접 조작 불필요)

`pogo-bot.js`는 git에는 올라가지만 Railway처럼 자동 배포되지 않습니다 - 대신 폰에 깔린 FTP 서버 앱(예: "FTP 서버" by xnano)과 MacroDroid 조합으로 원격 배포합니다:

1. 폰의 FTP 앱이 `/storage/emulated/0/msgbot/Bots/<봇이름>/`을 루트로 노출 (`<봇이름>.js`, `bot.json`, `modules/` 등이 보임)
2. PC에서 `curl -T messenger-bot/pogo-bot.js "ftp://<폰IP>:<포트>/<봇이름>.js" -u "<계정>:<비번>"`로 덮어쓰기
3. 폰의 MacroDroid 매크로가 파일 변경을 감지(`File Changed` 트리거)해서 `com.xfl.msgbot.broadcast.compile` 브로드캐스트를 자동 전송(`Send Intent` 액션, Extra `name`=봇이름) → 메신저봇R이 자동 재컴파일

ADB 무선 디버깅 페어링은 이 환경에서 계속 `protocol fault` 에러로 실패해서(원인 미상), 이 FTP+MacroDroid 방식으로 대체했습니다.

## Railway 환경 변수

기존 `DATABASE_URL`에 다음 값을 추가합니다.

- `AI_PROVIDER`: 기본값 `gemini`
- `GEMINI_API_KEY`: Google AI Studio에서 발급한 API 키
- `GEMINI_MODEL`: 기본값 `gemini-3.6-flash`
- `ADMIN_TOKEN`: 관리자 API에 사용할 충분히 긴 임의 문자열

실제 값은 저장소에 커밋하지 마세요. `.env.example`은 이름과 형식만 보여주는 예시입니다.

Groq로 전환하려면 `AI_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL`을 설정합니다. OpenAI로 전환하려면 `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`을 설정합니다. NVIDIA(NIM)로 전환하려면 `AI_PROVIDER=nvidia`, `NVIDIA_API_KEY`, 필요하면 `NVIDIA_MODEL`(기본값 `google/gemma-4-31b-it`)을 설정합니다. reasoning이 기본으로 켜진 모델(Nemotron 계열 등)은 내부적으로 "생각" 단계를 거치느라 이 수집기가 넘기는 큰 입력(수만 자)에서 응답이 매우 느려질 수 있어, reasoning이 기본 꺼짐인 모델을 기본값으로 씁니다. NVIDIA NIM 모델은 종종 서비스 종료(EOL)되니, 수집이 `410`/`model ... no longer available` 오류로 실패하면 [build.nvidia.com](https://build.nvidia.com/models)에서 현재 제공 중인 모델 ID로 `NVIDIA_MODEL`을 갱신하세요. 응답이 180초를 넘기면 (재시도 없이) 타임아웃으로 실패합니다(`APITimeoutError`). NVIDIA 무료 API는 이 수집기가 보내는 큰 입력(수만 자)에서 실제로 1~3분 정도 걸릴 수 있습니다 — Gemini보다 느립니다. NVIDIA NIM은 자체 웹 검색 기능이 없어서, Gemini와 마찬가지로 봇이 직접 가져온 공식 한국 뉴스 + 한국 커뮤니티 소스 텍스트를 구조화하는 방식으로 동작합니다. 선택하지 않은 공급자의 API 키는 필요하지 않습니다.

## 배포 후 최초 수집

Swagger `/docs`에서 `POST /api/admin/collect?days=30`을 실행하고 요청 헤더 `x-admin-token`에 Railway의 `ADMIN_TOKEN` 값을 넣습니다. 응답의 `found`, `inserted`, `updated`로 결과를 확인합니다.

기존 `events` 테이블은 삭제하지 않습니다. 앱 시작 시 필요한 열과 `collect_runs` 테이블이 자동으로 추가됩니다. 새 데이터는 출처 URL, 분류, 시작 시각을 해시한 `external_key`로 upsert됩니다 (제목은 소스가 바뀌어도 같은 이벤트로 인식되도록 키에서 제외).

## 이벤트 삭제

세 관리자 API 모두 `POST /api/admin/collect`와 같은 방식으로 `x-admin-token` 헤더가 필요합니다.

- `DELETE /api/admin/events/{event_id}`: 이벤트 하나를 id로 삭제합니다. 없는 id면 404를 반환합니다.
- `DELETE /api/admin/events/dedupe`: 분류·시작/종료 시각이 완전히 같은 중복 이벤트 중 오래된 행(가장 낮은 id)만 지우고 최신 행은 남깁니다. 출처 URL이 달라도(같은 실제 이벤트를 다른 소스로 다시 수집한 경우 등) 지웁니다. 매 수집 직후(`collect_events` 끝에서) 자동으로도 실행됩니다. 응답의 `removed`로 삭제된 개수를 확인합니다.
- `DELETE /api/admin/events/source?domain=leekduck.com`: 출처 URL에 해당 도메인이 포함된 이벤트를 전부 지웁니다. 더 이상 쓰지 않는 소스(예: leekduck.com)에서 예전에 수집돼 남아있는 행을 정리할 때 씁니다.

## 자동 수집

웹 서비스가 실행 중이면 같은 프로세스에서 한국 시간 06:00, 12:00, 18:00에 자동으로 30일 일정을 수집합니다. 별도 Railway Cron 서비스는 필요하지 않습니다. 끄려면 `AUTO_COLLECT_ENABLED=false`를 설정합니다. 서비스는 하나의 replica로 실행하는 것을 권장합니다.

앱 시작 시 예전에 생성된 `source_name=TEST` 테스트 일정은 자동으로 정리되며, 테스트 일정 생성용 관리자 API는 제공하지 않습니다.

## 로컬 실행과 테스트

```bash
python -m pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload
```

`DATABASE_URL`이 없으면 로컬 SQLite 파일을 사용합니다. 기본 설정으로 실제 일정을 수집하려면 `GEMINI_API_KEY`가 필요합니다.
