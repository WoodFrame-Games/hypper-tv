# Hypper Sandbox — гайд по подключению к Photon (0.5.0.8 / 0.5.0.9)

Один документ, в котором собрано всё: авторизация, UDP-протокол, готовый клиент,
как это было вскрыто и чем отличаются версии.

> **Обновлено под 0.5.0.9.** AppId, SecretKey, адрес сервера и UDP-протокол не
> изменились — меняется только `AppVersion`. Код вынесен в общий модуль
> `photon0509.py`, см. §9.

Проверено на живом сервере (0.5.0.9): Connect → Authenticate (`rc=0`) → JoinLobby →
список комнат (**48–51 комната** с картой, режимом, паролем, PvP, Nextbot).

---

## 1. Параметры подключения

| Параметр | Значение |
|---|---|
| AppId | `b6c0c507-d9ea-4e0b-ae1a-930bd1240323` (литерал прямо в `MainMenu.Connect`) |
| Сервер | `82.158.120.189:5055`, **UDP** (`UseNameServer = false`, без облака ExitGames) |
| AppVersion | `Application.version` = `0.5.0.8` (в 0.5.0.9 — `0.5.0.9`) |
| ClientVersion | `4.1.8.23` |
| Регион | не задаётся |
| Ассет PhotonServerSettings | `0a030a43-79e5-4bef-916d-da7e7fc885c6` — **устаревший, игнорируется** |

## 2. Авторизация

```
uid  = SystemInfo.deviceUniqueIdentifier
       (если пусто/"n/a" — PlayerPrefs["uid"] = Guid.NewGuid().ToString("N"))

sign = HMAC-SHA256(SecretKey, UTF8(uid))  ->  hex, ВЕРХНИЙ регистр

SecretKey = 5fbe710fbd13fcf332388fe3dac452b518b9b160ddf689c91d52eb1a69a0604e
```

Проверено на реальной паре из клиента:
`uid=bc57d0403bb30f8d1deaba727cca5d23` →
`sign=ACCF06056428DE56636C6A5CF2CA9EB9DF33D4887D9F1CEE4398AEC0F2721276` ✓

Подпись передаётся как `AuthGetParameters` (`s=<sign>`), `AuthType = Custom (0)`.
PlayFab к Photon отношения не имеет (остался только для логина/IAP/профиля,
TitleId `324C5`).

## 3. UDP-протокол (Photon EnetPeer)

### 3.1 Датаграмма — 12-байтный заголовок

```
[0..1]  peerId     u16 LE  (0xFFFF до Connect; после — VerifyConnect.payload[0:2] LE)
[2]     flags      u8      (0x00)
[3]     cmdCount   u8
[4..7]  sentTime   u32 BE  (мс от старта сессии)
[8..11] challenge  u32 BE  (случайный, постоянный на сессию)
```

> Важно: магического `F3 02` в заголовке датаграммы **нет** — это префикс payload
> операции (см. 3.3).

### 3.2 Команда — 12 байт

```
[0]     type      1=ACK 2=CONNECT 3=VERIFYCONNECT 5=PING 6=SENDRELIABLE 8=FRAGMENT
[1]     channel   255 = control, 0 = операции
[2]     flags     бит0 = reliable
[3]     reserved  = 0x04
[4..7]  size      u32 BE = 12 + длина payload
[8..11] seq       u32 BE
```

Сервер отвечает той же структурой; ACK-payload = `[ackedSeq u32 BE][эхо sentTime u32 BE]`.

### 3.3 Payload операции

```
запрос : F3 02 | opcode u8 | paramCount u8 | ([key u8][type][value])*
ответ  : F3 03 | opcode u8 | rc i16 BE | debugString | params
ивент  : F3 04 | eventCode u8 | paramCount u8 | params
```

Типы Protocol18: `7`=string(`len varint`+utf8), `9`=int varint, `3`=byte,
`4/13`=u16, `11/12`=i8, `5`=i32, `6`=double, `21`=dictionary,
`27/28`=false/true, `8`=null.

### 3.4 Подключение

1. **Connect** — `type=2, channel=255, flags=1, reserved=4`, payload 32 байта:

```
000004b0 00008000 00000000 02000000 00000000 00000000 00001388 00000002
```

2. Сервер присылает ACK + **VerifyConnect** (type 3, ch=255). Из его payload
   берём `peerId` = первые 2 байта (LE) — далее все пакеты идут с ним.
3. **Authenticate (op 230)** — `type=6, channel=0`:

| ключ | параметр | значение |
|---|---|---|
| 224 | AppId | `b6c0c507-…` |
| 220 | AppVersion | `0.5.0.8` |
| 223 | ClientVersion | `4.1.8.23` |
| 225 | UserId | uid |
| 217 | AuthType | `0` (Custom) |
| 216 | AuthGetParameters | `s=<sign>` |

4. Ответ `F3 03 E6 00 00 …` → `rc=0`; в параметрах приходит токен (`221`) и uid.
5. **JoinLobby (op 229)**: `(213, "")`, `(212, 0)`.

### 3.5 Список комнат

Ивент `F3 04 E6 01 DE …`: key **222** (GameList), тип **21** (словарь).

Формат словаря Protocol18: `[count varint]`, затем пары
`[keyType][key][typed value]` (тип значения у каждой пары свой).

Свойства комнаты:

| ключ | смысл |
|---|---|
| 255 / 243 | maxPlayers |
| 252 | playerCount |
| 254 | isVisible |
| 253 | isOpen |
| 251 | removed |
| `Map` (string) | карта (BaseV2, Desert, FlatGrass, City, Mars…) |
| `GameMode` (int) | 0=Free, 1=Private, 2=Adventure |
| `Password` | пароль комнаты |
| `PvP`, `Nextbot` | флаги |

Большие списки приходят **фрагментами** — команда `type=8`, payload:

```
[startSeq u32 BE][fragCount u32 BE][fragNum u32 BE][totalLen u32 BE][offset u32 BE][data]
```

После сборки всех фрагментов получаем `F3 04 …` ивент целиком.

---

## 4. Готовый клиент

`D:\OnlyforComparison\photon_list.py` — без зависимостей (только stdlib).

```bat
python photon_list.py                       :: дефолтный uid, живой список
python photon_list.py --uid <32hex>         :: любой uid (sign считается локально)
python photon_list.py --debug               :: hex-дамп всех датаграмм
python photon_list.py --host H --port P
```

Пример вывода:

```
=== Hypper 0.5.0.8 Room List ===
  82.158.120.189:5055  uid=bc57d0403bb30f8d1deaba727cca5d23
  auth OK, peerId=0xd4df

  как                       3/12  BaseV2    Free       pass=125 pvp=True
  <color=blue>PARKOUR</color>  9/20  Desert    4          pvp=True
  military warfare          3/20  FlatGrass 4          pvp=True
  Room 5643                 6/20  DesertV2  4          pass=321
  pack23                    2/4   Base      Adventure  pass=223356 nextbot=True
  ...
  Всего комнат: 23
```

### Для Telegram-бота

```python
import asyncio, subprocess, sys

async def get_rooms_text() -> str:
    p = await asyncio.create_subprocess_exec(
        sys.executable, r"D:\OnlyforComparison\photon_list.py",
        "--uid", "bc57d0403bb30f8d1deaba727cca5d23",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    return out.decode("utf-8", "replace")
```

Или импортом — `PhotonClient(...).connect()/authenticate()/join_lobby()/rooms()`
возвращает `{room_name: {players, max, map, gamemode, password, pvp, nextbot}}`.

---

## 5. Как это было вскрыто (кратко)

1. **Эмуляция** PGL-распаковки (`il2dat`/HypperDump): восстановлена метадата v31 и
   расшифрованные сегменты → runtime ELF.
2. **Реверс IL2CPP** (`full.ilc`/`dump.cs`): найдены `MainMenu.Connect/Sign/Secret/GetUserId`,
   `ServiceManager.LoginPlayFab`; расшифрован механизм строковых литералов
   (usage-слот → указатель → токен `(type<<29)|(idx<<1)`).
3. Выяснено, что **код в APK не зашифрован** (XOR исходного и расшифрованного
   образа в `.text` = 0), поэтому APK можно патчить напрямую.
4. Собран **логгер-патч** `libil2cpp.so`: ARM64-stub в code cave, перехват
   `MainMenu.Secret/Sign/GetUserId` и `EnetPeer.SendData` → `__android_log_print`.
   APK пересобран, подписан, установлен; данные сняты через `adb logcat`.
5. По логам восстановлены заголовок/команды/`F3 02`-payload, Connect-payload,
   peerId и полный список комнат; затем клиент написан заново и проверен вживую.

Отладочные материалы: `D:\tmp\opencode\build_stub*.py`, `patch_so*.py`,
`flow*.py`, `D:\tmp\opencode\h508\hypper_patched_signed.apk`.

---

## 6. Отличия от 0.5.0.7

| | 0.5.0.7 | 0.5.0.8 |
|---|---|---|
| AppId | `d74dbbe7-aba6-4827-91f9-acf2f2fb011f` + PlayFab TitleData `PhotonAppId` | `b6c0c507-…` (хардкод) |
| Сервер | NameServer ExitGames + регион `eu`, WebSocket | прямой UDP `82.158.120.189:5055` |
| AppVersion | `"gmnewg" + Application.version` | `Application.version` |
| Auth | PlayFab `GetPhotonAuthenticationToken` → токен (ключ 221) | своя HMAC-подпись (`s=`, ключ 216) |
| UserId | PlayFabId | deviceUniqueIdentifier / PlayerPrefs uid |

---

## 7. Траблшутинг

| Симптом | Что делать |
|---|---|
| `connect failed` | Проверить доступность `82.158.120.189:5055` (UDP), VPN/файрвол; сервер может быть недоступен |
| `auth failed` | Проверить `SECRET_KEY`/uid; sign = HMAC-SHA256(key, uid) **верхним** регистром |
| Комнат 0 | Подождать: список приходит фрагментами через 1–3 с после JoinLobby; повторить запуск |
| Краш на Android 12+ при установке патча | `resources.arsc` должен быть **без сжатия** и выровнен (`zipalign -p 4`) |
| Игра не запускается с patched APK | Переустановить оригинал (`adb uninstall com.Hypper`, `adb install` исходного APK) |

---

## 8. Файлы

| Файл | Назначение |
|---|---|
| `photon0509.py` | **общий модуль**: параметры билда, Protocol18, UDP EnetPeer (sync + async), сборка фрагментов, разбор списка комнат |
| `photon_list.py` | CLI списка комнат (тонкая обёртка над модулем) |
| `ptWorkFreeze.py` | интерактивный инструмент (лобби, комнаты, боты, RPC/чат) на том же транспорте |
| `selftest_ops.py` | самопроверка: connect → auth → lobby → ответ на операцию |
| `UDP_PROBE_RESULTS.md` | протокол и результаты подбора |
| `CONNECTION_CHAIN_0508.md` | разбор цепочки подключения по коду игры |
| `0.5.0.8/` | APK, расшифрованный `libil2cpp.so`, `global-metadata.dat` |
| `0.5.0.8/IL2IL`, `0.5.0.8/AssetRipper` | дампы кода и декомпилированные проекты |

---

## 9. Обновление под 0.5.0.9

### 9.1 Что изменилось в игре

Сверено с метадатой/ELF 0.5.0.9 (`full059`) и логом живого клиента
(`SupportLogger`: `AppVersion: "0.5.0.9"`, `Client: v4.1.8.23`, `Socket: SocketUdp`,
`AuthType: Custom`, `Current Server: 82.158.120.189:5055`):

| Параметр | 0.5.0.8 | 0.5.0.9 |
|---|---|---|
| AppId | `b6c0c507-…` | **тот же** (строка есть в метадате) |
| Сервер | `82.158.120.189:5055` UDP | **тот же** |
| ClientVersion | `4.1.8.23` | **тот же** |
| AppVersion | `0.5.0.8` | **`0.5.0.9`** |
| SecretKey / схема подписи | HMAC(`s=`) | **та же** (проверено входом `rc=0`) |
| Протокол (EnetPeer + `F3 02/03/04`) | — | **без изменений** |

`NameServer: ns.photonengine.io` в логе игры — это поле настроек, оно не
используется: клиент идёт напрямую на `82.158.120.189:5055`.

### 9.2 Что сделано в коде

1. **`photon0509.py`** — единая реализация протокола (stdlib, без aiohttp/websockets):
   - `PhotonUdp` — синхронный EnetPeer: `connect()` → `authenticate()` →
     `join_lobby()` → `collect_rooms()`, ACK-и, сборка фрагментов, полный список
     комнат по ивенту 230 (и 229 для апдейтов);
   - `AsyncPhotonUdp` — тот же клиент с async-интерфейсом старого WS-класса
     (`connect/send_operation/receive/receive_timeout/aclose`), блокирующие
     вызовы уходят в поток;
   - все параметры билда в одном месте, переопределяются переменными окружения
     `HYPPER_PHOTON_HOST/PORT/UID`.
2. **`photon_list.py`** переписан как тонкий CLI: `--uid`, `--host/--port`,
   `--ver`, `--seconds/--idle`, `--json`. Главное исправление — сбор списка:
   раньше цикл выходил после первой распарсенной комнаты (`if rooms: break`) и
   терял остальные фрагменты; теперь ждём до «тишины» `--idle` секунд. Было
   2 комнаты, стало 48–51.
3. **`ptWorkFreeze.py`** переведён с цепочки PlayFab → NameServer → WebSocket на
   прямое UDP:
   - PlayFab-логин и токен заменены на uid + `sign_for(uid)`; `playfab_login`/
     `get_photon_token` оставлены как no-op ради остального кода (боты);
   - `connect_to_name_server()` = CONNECT → Authenticate → JoinLobby на
     `PHOTON_HOST:PORT`; `connect_to_master()` = то же; `connect_to_game_server()`
     переподключается на адрес из ответа (в 0.5.0.9 это тот же узел);
   - `_build_auth_op_full()` — новая авторизация (224/220/223/225/217/216);
   - `aiohttp`/`websockets` больше не обязательны (импорт опционален);
   - ping-и идут через EnetPeer-PING (`send_ping()`), а не WS-сообщение.

### 9.3 Проверка

```bat
python photon_list.py            :: список комнат (48-57 шт.)
python photon_list.py --json     :: машинный формат
python selftest_ops.py           :: connect/auth/lobby + ответ на операцию
python ptWorkFreeze.py           :: интерактивно; RoomList / CreateRoom / Join
```

Результат прогона: `connect OK, peerId=0x48b1`, `auth rc=0`, **48–57** комнат,
у каждой — `max/players/map/gamemode/password/pvp/nextbot` (см. §3.5).

Подпись для эталонного uid совпала с гайдом: `uid=bc57d0403bb30f8d1deaba727cca5d23`
→ `sign=ACCF06056428DE56636C6A5CF2CA9EB9DF33D4887D9F1CEE4398AEC0F2721276` —
значит SecretKey и схема HMAC в 0.5.0.9 не менялись.

### 9.4 Ограничение сервера на новые uid

Сервер разрешает авторизацию только уже известным `UserId`; для новых
отвечает одним из двух кодов:

| rc | debug-строка | смысл |
|---|---|---|
| `-2689` | `InvalidAuthentication` | uid серверу неизвестен |
| `32757` | `Too many accounts from this address` | превышен лимит регистраций с IP |

Поэтому uid клиента теперь **стабильный** (`photon_uid.txt` рядом с модулем,
как `deviceUniqueIdentifier` у игры), а при отказе оба скрипта один раз
повторяют вход с известным `FALLBACK_UID` (`bc57d040…`), печатают
предупреждение и **запоминают рабочий uid** — следующий запуск заходит сразу.
Переопределение: `--uid` / `$HYPPER_UID`.

Отдельно: uid, который сейчас играет в игре, занять нельзя — сервер вернёт
`rc=-2689` (одна сессия на UserId). Так, uid из лога SupportLogger
(`52c2436f…`) авторизуется только после выхода из игры.

Наблюдение: `JoinRoom` (op 226) для заведомо несуществующей комнаты вернул
`rc=0` — сервер не отдаёт ошибку в ответе на операцию; поведение игры в этом
случае не проверялось.