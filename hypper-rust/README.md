# hypper-rust

Перенос клиента Hypper (стена мониторов с видео) с Python на Rust — для нативного APK.

## Статус

| Шаг | Состояние |
|---|---|
| UDP EnetPeer: CONNECT → VERIFY (peerId) | готово |
| ACK всех команд, PING, фрагментация по MTU 1200, ретрансмит | готово |
| Protocol18: varint, CompressedInt (LE), строки, массивы, хештаблицы | готово |
| Authenticate (op 230, HMAC-подпись uid) | готово, `rc = 0` |
| JoinLobby (op 229) | отправляется |
| CreateRoom (op 227) на мастер-сервере → GS-адрес + токен | готово, `rc = 0` |
| Game Server: auth по токену + CreateRoom = вход, actorNr | готово, `actor = Some(1)` |
| Спавн монитора (RaiseEvent 202 + Instantiate) | не начато |
| Поток кадров (RaiseEvent 206) | не начато |
| GUI (egui) поверх core | не начато |
| Android-сборка (NDK, android-activity, APK) | не начато |

## Проверка

```bash
cd C:\Work\Hypper\hypper-rust
cargo run --bin probe            # uid и имя комнаты по умолчанию
cargo run --bin probe <uid> <room>
```

Ожидаемый вывод:

```
master auth rc = 0
create rc = 0  gs = 82.158.120.189:27002  token = ...
gs auth rc = 0
gs create rc = 0
actor = Some(1)
```

`$env:HYPPER_RUST_DEBUG=1` — печать всех датаграмм.

## Что выяснено по ходу порта

- одиночный байт кодируется как `0x22` (ноль) или `0x03 <b>`, а не как byte[] `0x79`;
- `build_op` в Python возвращает тело операции без `F3 02` — префикс добавляется при отправке;
- ответ операции: `[op][rc lo][rc hi][debug value][paramCount][key][type][value]...`,
  где debug value тоже типизирован (0x08 — пусто);
- двухбайтовые CompressedInt — little-endian (иначе 1000 читается как 59395);
- actorNr приходит параметром 254 в ответе CreateGame на игровом сервере.