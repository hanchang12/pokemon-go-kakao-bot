# Pokemon GO Kakao Bot

카카오톡 메신저봇 API2, Railway FastAPI, PostgreSQL을 연결해 Pokemon GO 일정을 답하는 봇입니다. OpenAI Responses API의 Web Search와 Structured Outputs로 한국 기준 30일 일정을 수집하고, 동일 이벤트는 중복 저장하지 않고 갱신합니다.

## 지원 명령어

- `포고봇 오늘`, `포고봇 내일`, `포고봇 이번주`
- `포고봇 레이드`, `포고봇 레이드아워`
- `포고봇 스포트라이트`, `포고봇 커뮤`
- `포고봇 다음 이벤트`, `포고봇 지금 뭐해`
- `포고봇 도움말`, `포고봇 테스트`

## Railway 환경 변수

기존 `DATABASE_URL`에 다음 값을 추가합니다.

- `OPENAI_API_KEY`: OpenAI API 키
- `OPENAI_MODEL`: 기본값 `gpt-5.4-mini`
- `ADMIN_TOKEN`: 관리자 API에 사용할 충분히 긴 임의 문자열

실제 값은 저장소에 커밋하지 마세요. `.env.example`은 이름과 형식만 보여주는 예시입니다.

## 배포 후 최초 수집

Swagger `/docs`에서 `POST /api/admin/collect?days=30`을 실행하고 요청 헤더 `x-admin-token`에 Railway의 `ADMIN_TOKEN` 값을 넣습니다. 응답의 `found`, `inserted`, `updated`로 결과를 확인합니다.

기존 `events` 테이블은 삭제하지 않습니다. 앱 시작 시 필요한 열과 `collect_runs` 테이블이 자동으로 추가됩니다. 새 데이터는 제목, 분류, 시작 시각을 해시한 `external_key`로 upsert됩니다.

## 자동 수집

Railway에서 같은 저장소를 사용하는 Cron 서비스를 하나 더 만들고 실행 명령을 아래처럼 지정합니다.

```text
python -m app.collect_once
```

한국 시간 06:00과 18:00에 실행하려면 UTC cron 표현식은 `0 21,9 * * *`입니다. Cron 서비스에도 웹 서비스와 동일한 `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` 환경 변수가 필요합니다.

## 로컬 실행과 테스트

```bash
python -m pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload
```

`DATABASE_URL`이 없으면 로컬 SQLite 파일을 사용합니다. 실제 일정 수집에는 `OPENAI_API_KEY`가 필요합니다.
