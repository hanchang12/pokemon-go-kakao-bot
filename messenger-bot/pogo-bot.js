/**
 * Pokemon GO 카카오봇 - 메신저봇R (API2) 스크립트
 *
 * 설치
 *  1) 메신저봇R 앱 → 새 봇 만들기 → 이름: pogo-bot (API2 선택)
 *  2) 이 파일 내용을 전체 붙여넣기
 *  3) 저장 후 컴파일(▶) → 봇 전원 ON
 *  4) 메신저봇R 앱에 "알림 접근 권한" 허용 확인
 *  5) 카카오톡에서 "/포고봇 테스트" 전송
 *
 * 이 앱 버전에서는 메시지 수신을 function response(...) 전역 훅이 아니라
 * bot.addListener(Event.MESSAGE, ...) 이벤트 리스너로 등록해야 실제로
 * 호출된다(직접 확인됨 - 전역 훅 방식은 켜져 있어도 한 번도 안 불렸다).
 *
 * 예약 발송("/포고봇 예약 09:00" 등)이 동작하려면 서버에 쌓인 대기열을 주기적으로
 * 확인해서 bot.send()로 방에 전달해야 하는데, JS 엔진 쪽 타이머(setInterval,
 * Event.TICK)는 이 메신저봇R 빌드에서 실제로 호출되지 않는 것이 확인됐다(앱
 * UI에도 별도 예약/매크로 메뉴가 없음). 대신 JS 이벤트 루프를 거치지 않는
 * 순수 Java 스레드(java.lang.Thread + Thread.sleep 무한루프)로 직접 타이머를
 * 돌린다 - bot.send()/Jsoup 호출은 LiveConnect로 노출된 Java 메서드라 어느
 * 스레드에서 불러도 동작하므로, 채팅이 전혀 없어도 설정한 간격마다 큐를 확인해
 * 보낼 수 있다(startDuePoller 참고). Event.MESSAGE 쪽 폴링은 채팅이 왔을 때
 * 더 빠르게 전달하기 위한 보조 경로로 남겨둔다.
 *
 * "/포고봇 수집"과 도움말에 없는 자유 질문(AI 답변)만은 이 폴링에 안 기댄다 -
 * 첫 응답("시작했어요"/"확인하고 있어요") 직후 같은 흐름에서 바로 긴(4분)
 * 블로킹 호출(POST /api/collect 또는 /api/ask)로 결과를 받아 두 번째
 * msg.reply()로 보낸다. 다른 채팅이 와야만 결과가 오는 문제를 이걸로 피한다.
 *
 * 서버: FastAPI on Railway, POST /api/messages, POST /api/collect, POST /api/ask,
 * GET /api/subscriptions/due
 */

const SERVER_URL = "https://pokemon-go-kakao-bot-production.up.railway.app";
const PREFIX = "/포고봇";
const TIMEOUT_MS = 12000;
const BLOCKING_TIMEOUT_MS = 240000; // 수집/AI질문 두 번째(블로킹) 호출 - 최대 4분 대기
const POLL_DEBOUNCE_MS = 20000; // 메시지 트리거 폴링 최소 간격 (20초)
var lastPollAt = 0;

const Jsoup = org.jsoup.Jsoup;
const bot = BotManager.getCurrentBot();

function askServer(room, sender, message, isGroupChat) {
  const payload = JSON.stringify({
    room: room,
    sender: sender,
    message: message,
    is_group_chat: isGroupChat,
  });

  const responseText = Jsoup.connect(SERVER_URL + "/api/messages")
    .header("Content-Type", "application/json")
    .requestBody(payload)
    .ignoreContentType(true)
    .ignoreHttpErrors(true)
    .timeout(TIMEOUT_MS)
    .post()
    .text();

  return JSON.parse(responseText);
}

/* "포고봇 수집"/AI 질문의 두 번째(블로킹) 호출 - 실제 처리가 끝날 때까지
   기다렸다가 결과 문구를 받아온다. 첫 호출의 즉시 응답과 달리 몇 분씩 걸릴
   수 있어 타임아웃을 훨씬 길게 잡는다. */
function runCollectBlocking() {
  const res = Jsoup.connect(SERVER_URL + "/api/collect")
    .ignoreContentType(true)
    .ignoreHttpErrors(true)
    .timeout(BLOCKING_TIMEOUT_MS)
    .method(org.jsoup.Connection.Method.POST)
    .execute();

  const data = JSON.parse(res.body());
  return data.reply;
}

function runAskBlocking(room, sender, question) {
  const payload = JSON.stringify({ room: room, sender: sender, message: question });

  const responseText = Jsoup.connect(SERVER_URL + "/api/ask")
    .header("Content-Type", "application/json")
    .requestBody(payload)
    .ignoreContentType(true)
    .ignoreHttpErrors(true)
    .timeout(BLOCKING_TIMEOUT_MS)
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
    const data = askServer(msg.room, msg.author.name, text, msg.isGroupChat);
    const reply = data.reply;

    // 서버가 reply: null 을 주면 인식하지 못한 명령 → 도움말 안내
    if (reply === null || reply === undefined || reply === "") {
      msg.reply("❓ 알 수 없는 명령입니다.\n'/포고봇 도움말' 을 입력해 보세요.");
      return;
    }

    msg.reply(reply);

    // 수집 시작/AI 질문 확인 응답이면, 같은 흐름 안에서 바로 이어서 완료를
    // 기다렸다가 보낸다. (예전엔 다른 채팅이 와야만 결과가 배달되는 폴링 방식이었음)
    if (data.await_collect) {
      try {
        const collectResult = runCollectBlocking();
        msg.reply(collectResult || "⚠️ 수집 결과를 받지 못했습니다.");
      } catch (e2) {
        msg.reply("⚠️ 수집 완료 확인 중 오류\n" + e2);
      }
    } else if (data.await_ask) {
      try {
        const askResult = runAskBlocking(msg.room, msg.author.name, text);
        msg.reply(askResult || "⚠️ 답변을 받지 못했습니다.");
      } catch (e3) {
        msg.reply("⚠️ 답변 확인 중 오류\n" + e3);
      }
    }
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

/* setInterval이 안 도는 환경 대응: 메시지 수신 이벤트마다 대신 확인한다
   (채팅이 있을 때 더 빠르게 전달하기 위한 보조 경로 - 메인 경로는
   startDuePoller의 백그라운드 스레드) */
function maybePollDueSubscriptions() {
  var now = new Date().getTime();
  if (now - lastPollAt < POLL_DEBOUNCE_MS) return;
  lastPollAt = now;
  pollDueSubscriptions();
}

const DUE_POLL_INTERVAL_MS = 30000; // 채팅과 무관하게 30초마다 예약 큐 확인
const DUE_POLLER_THREAD_NAME = "pogo-bot-due-poller";

/* 이미 같은 이름의 폴링 스레드가 떠 있는지 확인한다. 스크립트가 재컴파일되면
   JS 쪽 전역 변수는 초기화되지만, 이전 컴파일에서 띄운 Java 스레드는 그대로
   살아있을 수 있어 중복 스레드가 쌓이는 걸 막기 위한 안전장치다. */
function isDuePollerRunning() {
  try {
    var threads = java.lang.Thread.getAllStackTraces().keySet().toArray();
    for (var i = 0; i < threads.length; i++) {
      if (String(threads[i].getName()) === DUE_POLLER_THREAD_NAME) return true;
    }
  } catch (e) {
    Log.e("폴링 스레드 중복 확인 실패: " + e);
  }
  return false;
}

/* 채팅과 완전히 무관하게 동작하는 예약 발송의 메인 경로. JS 엔진의 이벤트
   루프(setInterval/Event.TICK)에 기대지 않고, 순수 Java 스레드를 만들어
   그 안에서 Thread.sleep으로 직접 주기를 돈다 - bot.send()/Jsoup 호출은
   Java 메서드라 이 스레드에서 불러도 그대로 동작한다. */
function startDuePoller() {
  if (isDuePollerRunning()) {
    Log.i("예약 폴링 스레드가 이미 실행 중입니다.");
    return;
  }
  var thread = new java.lang.Thread(function () {
    while (true) {
      try {
        java.lang.Thread.sleep(DUE_POLL_INTERVAL_MS);
        pollDueSubscriptions();
      } catch (e) {
        Log.e("예약 백그라운드 폴링 중 오류: " + e);
      }
    }
  });
  thread.setName(DUE_POLLER_THREAD_NAME);
  thread.setDaemon(true);
  thread.start();
  Log.i("예약 백그라운드 폴링 스레드 시작 (" + DUE_POLL_INTERVAL_MS + "ms 간격, 채팅 없어도 동작)");
}

startDuePoller();

/* 컴파일 시 1회 호출됨. 위 startDuePoller()는 스크립트 로드 시점에 이미
   실행되지만, 컴파일 타이밍에 한 번 더 확인해 혹시 스레드가 죽어 있으면
   재시작한다(중복 방지 체크가 있어 안전하다). */
function onStartCompile() {
  Log.i("pogo-bot 컴파일 완료 / 서버: " + SERVER_URL);
  startDuePoller();
}
