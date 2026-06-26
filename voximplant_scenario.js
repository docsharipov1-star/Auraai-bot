/**
 * Сценарий голосового робота для стоматологии
 * Вставить в Voximplant Dashboard → Applications → Scenarios
 */

require(Modules.VoicePlayer);

var MESSAGES = {
    confirm: {
        greeting: "Здравствуйте! Вам звонит автоматический помощник стоматологической клиники. " +
                  "Напоминаем о вашей записи {date} в {time}. " +
                  "Нажмите 1, чтобы подтвердить запись. Нажмите 2, если не сможете прийти.",
        confirmed: "Отлично, спасибо! Ждём вас. Если понадобится перенести запись — позвоните нам. До свидания!",
        cancelled: "Хорошо, мы отменим вашу запись. Чтобы перезаписаться — позвоните нам. До свидания!",
        no_answer:  "Пожалуйста, нажмите 1 для подтверждения или 2 для отмены записи.",
        timeout:    "Мы не получили ответа. Пожалуйста, перезвоните нам для подтверждения. До свидания!"
    },
    review: {
        greeting: "Здравствуйте! Вам звонит помощник стоматологической клиники. " +
                  "Вы недавно посетили нас. Пожалуйста, оцените качество обслуживания. " +
                  "Нажмите 1 — отлично, нажмите 2 — хорошо, нажмите 3 — плохо.",
        great:   "Спасибо за отличную оценку! Будем рады видеть вас снова. До свидания!",
        good:    "Спасибо за оценку! Мы стараемся стать лучше. До свидания!",
        bad:     "Нам жаль. Мы обязательно разберёмся и улучшим качество. Спасибо за честность. До свидания!"
    }
};

var customData = {};
try {
    customData = JSON.parse(VoxEngine.customData()) || {};
} catch(e) {}

var callType  = customData.call_type || "confirm";
var date      = customData.date || "завтра";
var time      = customData.time || "";
var adminUid  = customData.admin_uid || "";
var phone     = customData.phone || "";

var msg = MESSAGES[callType] || MESSAGES.confirm;
var greeting = msg.greeting.replace("{date}", date).replace("{time}", time);

var resultCode = "no_answer";
var dtmfReceived = false;
var player;

VoxEngine.addEventListener(AppEvents.CallAlerting, function(e) {
    var call = e.call;

    call.addEventListener(CallEvents.Connected, function() {
        player = new VoicePlayer();
        player.say(greeting, Language.RU_RUSSIAN_FEMALE);

        // Ждём нажатия кнопки
        call.addEventListener(CallEvents.ToneReceived, function(dtmf) {
            dtmfReceived = true;
            var tone = dtmf.tone;

            if (callType === "confirm") {
                if (tone === "1") {
                    resultCode = "confirmed";
                    player.say(msg.confirmed, Language.RU_RUSSIAN_FEMALE);
                } else if (tone === "2") {
                    resultCode = "cancelled";
                    player.say(msg.cancelled, Language.RU_RUSSIAN_FEMALE);
                } else {
                    player.say(msg.no_answer, Language.RU_RUSSIAN_FEMALE);
                }
            } else if (callType === "review") {
                if (tone === "1") {
                    resultCode = "great";
                    player.say(msg.great, Language.RU_RUSSIAN_FEMALE);
                } else if (tone === "2") {
                    resultCode = "good";
                    player.say(msg.good, Language.RU_RUSSIAN_FEMALE);
                } else if (tone === "3") {
                    resultCode = "bad";
                    player.say(msg.bad, Language.RU_RUSSIAN_FEMALE);
                }
            }

            setTimeout(function() {
                sendResult(call);
            }, 3000);
        });

        // Таймаут 15 секунд если не нажал
        setTimeout(function() {
            if (!dtmfReceived) {
                resultCode = "no_answer";
                player.say(msg.timeout, Language.RU_RUSSIAN_FEMALE);
                setTimeout(function() {
                    sendResult(call);
                }, 3000);
            }
        }, 15000);
    });

    call.addEventListener(CallEvents.Failed, function() {
        resultCode = "failed";
        sendWebhook();
        VoxEngine.terminate();
    });

    call.addEventListener(CallEvents.Disconnected, function() {
        if (!dtmfReceived) {
            resultCode = "hung_up";
            sendWebhook();
        }
        VoxEngine.terminate();
    });

    call.answer();
});

function sendResult(call) {
    sendWebhook();
    call.hangup();
}

function sendWebhook() {
    var webhookUrl = customData.webhook_url || "";
    if (!webhookUrl) return;

    Net.httpRequest(webhookUrl + "?phone=" + encodeURIComponent(phone) +
        "&result=" + resultCode +
        "&call_type=" + callType +
        "&admin_uid=" + adminUid,
        function(e) {}
    );
}
