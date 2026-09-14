/**
 * Pokemon GO 카카오봇 - 메신저봇R (API2) 스크립트
 *
 * 설치
 *  1) 메신저봇R 앱 → 새 봇 만들기 → 이름: pogo-bot (API2 선택)
 *  2) 이 파일 내용을 전체 붙여넣기
 *  3) 저장 후 컴파일(▶) → 봇 전원 ON
 *  4) 메신저봇R 앱에 "알림 접근 권한" 허용 확인
 *  5) 카카오톡에서 "포고봇 테스트" 전송
 *
 * 이 앱 버전에서는 메시지 수신을 function response(...) 전역 훅이 아니라
 * bot.addListener(Event.MESSAGE, ...) 이벤트 리스너로 등록해야 실제로
 * 호출된다(직접 확인됨 - 전역 훅 방식은 켜져 있어도 한 번도 안 불렸다).
 *
 * 예약 발송("포고봇 예약 09:00" 등)이 동작하려면 서버에 쌓인 대기열을 주기적으로
 * 확인해서 bot.send()로 방에 전달해야 하는데, 이 메신저봇R 빌드에서는 채팅과
 * 무관한 자동 실행 수단이 전부 안 먹는다 - setInterval은 재컴파일 직후에도 한
 * 번도 안 불렸고, Event.TICK도 등록은 되지만 실제로 발생하지 않는 것이 로그로
 * 확인됐고, 앱 UI에도 별도 예약/매크로 메뉴가 없다. 유일하게 확실히 불리는 건
 * Event.MESSAGE뿐이라, 아무 메시지나 올 때마다(포고봇 접두사 없어도) 대기열을
 * 확인하는 방식으로 대신한다. 한계: 봇이 있는 모든 방을 통틀어 한동안 메시지가
 * 전혀 없으면 그동안은 예약 발송도 안 나간다 - 방 하나라도 활동이 있으면
 * 폴링이 전체 큐를 한 번에 처리하므로 조용한 방 것도 같이 배달된다.
 *
 * 서버: FastAPI on Railway, POST /api/messages, GET /api/subscriptions/due
 */

const SERVER_URL = "https://pokemon-go-kakao-bot-production.up.railway.app";
const PREFIX = "포고봇";
const TIMEOUT_MS = 12000;
const POLL_DEBOUNCE_MS = 20000; // 메시지 트리거 폴링 최소 간격 (20초)
var lastPollAt = 0;

const Jsoup = org.jsoup.Jsoup;
const bot = BotManager.getCurrentBot();

function askServer(room, sender, message) {
  const payload = JSON.stringify({ room: room, sender: sender, message: message });

  const responseText = Jsoup.connect(SERVER_URL + "/api/messages")
    .header("Content-Type", "application/json")
    .requestBody(payload)
    .ignoreContentType(true)
    .ignoreHttpErrors(true)
    .timeout(TIMEOUT_MS)
    .post()
    .text();

  const data = JSON.parse(responseText);
  return data.reply;
}

bot.addListener(Event.MESSAGE, function (msg) {
  maybePollDueSubscriptions();

  const text = String(msg.content).trim();

  // 접두사가 없으면 명령 처리는 하지 않음 (위의 폴링 체크는 이미 실행됨)
  if (text.indexOf(PREFIX) !== 0) return;

  try {
    const reply = askServer(msg.room, msg.author.name, text);

    // 서버가 reply: null 을 주면 인식하지 못한 명령 → 도움말 안내
    if (reply === null || reply === undefined || reply === "") {
      msg.reply("❓ 알 수 없는 명령입니다.\n'포고봇 도움말' 을 입력해 보세요.");
      return;
    }

    msg.reply(reply);
  } catch (e) {
    msg.reply("⚠️ 포고봇 서버 연결 오류\n" + e);
  }
});

/* 예약 발송 확인: 서버가 "지금 보낼 방" 목록을 주면 각 방에 직접 전송한다 */
function pollDueSubscriptions() {
  try {
    const res = Jsoup.connect(SERVER_URL + "/api/subscriptions/due")
      .ignoreContentType(true)
      .ignoreHttpErrors(true)
      .timeout(TIMEOUT_MS)
      .method(org.jsoup.Connection.Method.GET)
      .execute();

    if (res.statusCode() !== 200) {
      Log.e("예약 확인 실패: HTTP " + res.statusCode());
      return;
    }

    const data = JSON.parse(res.body());
    for (var i = 0; i < data.items.length; i++) {
      var item = data.items[i];
      bot.send(item.room, item.message);
    }
  } catch (e) {
    Log.e("예약 확인 중 오류: " + e);
  }
}

/* setInterval이 안 도는 환경 대응: 메시지 수신 이벤트마다 대신 확인한다 */
function maybePollDueSubscriptions() {
  var now = new Date().getTime();
  if (now - lastPollAt < POLL_DEBOUNCE_MS) return;
  lastPollAt = now;
  pollDueSubscriptions();
}

/* 컴파일 시 1회 호출됨 - setInterval/Event.TICK 둘 다 이 빌드에서 안 불려서
   더 이상 여기서 타이머를 등록하지 않는다 (Event.MESSAGE 트리거로 대체). */
function onStartCompile() {
  Log.i("pogo-bot 컴파일 완료 / 서버: " + SERVER_URL);
}
