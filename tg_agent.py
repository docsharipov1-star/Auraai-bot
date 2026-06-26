"""
Telegram агент — отправляет команды боту и читает ответы.
Запуск: python3 tg_agent.py
"""
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser

API_ID   = 39654408
API_HASH = "000d5d5beb82ab9a42a60f94206f70b5"
BOT_USERNAME = "GetAuraAI_bot"
SESSION  = "aura_session"

client = TelegramClient(SESSION, API_ID, API_HASH)

async def send_and_wait(command: str, wait_sec: int = 15) -> str:
    """Отправляет команду боту и ждёт ответа."""
    bot = await client.get_entity(BOT_USERNAME)
    await client.send_message(bot, command)
    print(f"📤 Отправлено: {command}")
    await asyncio.sleep(wait_sec)
    msgs = await client.get_messages(bot, limit=5)
    responses = []
    for m in reversed(msgs):
        if m.out:
            break
        responses.append(m.text or "")
    return "\n---\n".join(responses)

async def test_bot():
    """Тестирует бот и возвращает результаты."""
    print("🤖 Подключаюсь к Telegram...")
    await client.start()
    print("✅ Подключён!")

    results = {}

    # 1. Проверяем /zpdiag
    print("\n1️⃣ Проверяю /zpdiag...")
    r = await send_and_wait("/zpdiag", 20)
    results["zpdiag"] = r
    print(f"Ответ: {r[:500]}")

    # 2. Синхронизируем ЗП
    print("\n2️⃣ Синхронизирую ЗП таблицы...")
    r = await send_and_wait("/zpsync", 30)
    results["zpsync"] = r
    print(f"Ответ: {r[:500]}")

    # 3. Нажимаем Доктора
    print("\n3️⃣ Проверяю отчёт по врачам...")
    r = await send_and_wait("📊 Доктора", 15)
    results["doctors"] = r
    print(f"Ответ: {r[:500]}")

    return results

async def main():
    await client.start()
    print("✅ Авторизован!")
    print("\nАгент готов. Введи команду для отправки боту (или 'test' для полного теста):")

    while True:
        cmd = input("\nКоманда > ").strip()
        if not cmd:
            continue
        if cmd == "test":
            await test_bot()
        elif cmd == "exit":
            break
        else:
            r = await send_and_wait(cmd, 10)
            print(f"\n🤖 Ответ бота:\n{r[:2000]}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
