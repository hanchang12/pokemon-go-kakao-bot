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
 * 예약 발송("포고봇 예약 09:00" 등)이 동작하려면 이 스크립트가 계속 켜져
 * 있어야 합니다 - 서버는 카카오톡 방에 직접 메시지를 보낼 수 없어서, 이
 * 스크립트가 주기적으로 서버에 "보낼 예약 있어?"라고 물어보고(POLL_INTERVAL_MS
 * 간격) bot.send()로 직접 방에 전달하는 방식입니다.
 *
 * 서버: FastAPI on Railway, POST /api/messages, GET /api/subscriptions/due
 */

const SERVER_URL = "https://pokemon-go-kakao-bot-production.up.railway.app";
const PREFIX = "포고봇";
const TIMEOUT_MS = 12000;
const POLL_INTERVAL_MS = 60000; // 예약 발송 확인 주기 (1분)

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
  const text = String(msg.content).trim();

  // 접두사가 없으면 완전히 무시 (일반 대화에 반응하지 않음)
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

/* 메신저봇R 편집기에서 버튼으로 직접 실행해 볼 때 사용 / 컴파일 시 1회 호출됨 */
function onStartCompile() {
  Log.i("pogo-bot 컴파일 완료 / 서버: " + SERVER_URL);

  try {
    setInterval(pollDueSubscriptions, POLL_INTERVAL_MS);
  } catch (e) {
    Log.e("예약 폴링 타이머 등록 실패: " + e);
  }
}
