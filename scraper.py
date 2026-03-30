import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://rmk.stavedu.ru:8010/moodle"
LOGIN_URL = "https://rmk.stavedu.ru:8010/moodle/login/index.php"
DIARY_URL = "https://rmk.stavedu.ru:8010/moodle/eioswork/diaries/studentsdiary.php"

async def get_login_token(session: aiohttp.ClientSession) -> str:
    """Moodle требует logintoken с формы"""
    try:
        print(f"[DEBUG] Запрашиваем страницу логина...")
        async with session.get(LOGIN_URL, allow_redirects=True, max_redirects=5) as resp:
            print(f"[DEBUG] Статус ответа: {resp.status}")
            print(f"[DEBUG] URL после редиректов: {resp.url}")
            html = await resp.text()
            print(f"[DEBUG] Длина HTML: {len(html)} символов")
            
        soup = BeautifulSoup(html, "html.parser")
        token = soup.find("input", {"name": "logintoken"})
        
        if token:
            print(f"[DEBUG] Найден logintoken: {token['value'][:20]}...")
            return token["value"]
        else:
            print(f"[DEBUG] logintoken не найден в HTML")
            # Попробуем найти форму логина
            login_form = soup.find("form", {"id": "login"})
            print(f"[DEBUG] Форма логина найдена: {login_form is not None}")
            return ""
    except Exception as e:
        print(f"[DEBUG] Ошибка при получении logintoken: {e}")
        return ""

async def login(username: str, password: str) -> dict | None:
    """Возвращает куки если успешно, иначе None"""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            token = await get_login_token(session)
            print(f"[DEBUG] logintoken: {token[:20] if token else 'НЕТ'}...")
            print(f"[DEBUG] username: {username}")

            data = {
                "anchor": "",
                "logintoken": token,
                "username": username,
                "password": password,
            }

            async with session.post(LOGIN_URL, data=data, allow_redirects=True) as resp:
                final_url = str(resp.url)
                print(f"[DEBUG] final URL: {final_url}")

                # Успех — редиректнуло на /moodle/ а не обратно на login
                if "login" in final_url:
                    print(f"[DEBUG] Остались на странице логина - неверные данные")
                    return None

                cookies = {}
                for name, cookie in session.cookie_jar.filter_cookies(LOGIN_URL).items():
                    cookies[name] = cookie.value
                print(f"[DEBUG] cookies: {list(cookies.keys())}")
                return cookies if cookies else None
    except Exception as e:
        print(f"[ERROR] Ошибка подключения при логине: {e}")
        return None

async def fetch_grades(cookies: dict, year: int = None, month: int = None) -> str | None:
    """Получает и парсит оценки за месяц"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month

    url = f"{DIARY_URL}?year={year}&month={month}"
    print(f"[DEBUG] Запрашиваем оценки: {url}")
    print(f"[DEBUG] Используем куки: {list(cookies.keys())}")
    
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)

    try:
        async with aiohttp.ClientSession(connector=connector, cookies=cookies, timeout=timeout) as session:
            async with session.get(url) as resp:
                final_url = str(resp.url)
                html = await resp.text()
                print(f"[DEBUG] diary URL: {final_url}")
                print(f"[DEBUG] HTML length: {len(html)}")

                if "login" in final_url or "403" in html:
                    print(f"[DEBUG] Ошибка доступа или сессия протухла")
                    return None

        return parse_grades(html, year, month)
    except Exception as e:
        print(f"[ERROR] Ошибка подключения к серверу: {e}")
        return "❌ Сервер недоступен. Попробуй позже."

def parse_grades(html: str, year: int, month: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    
    print(f"[DEBUG] Парсим оценки...")
    
    table = soup.find("table", id="tblgrades")
    if not table:
        print(f"[DEBUG] Таблица tblgrades не найдена")
        # Попробуем найти любую таблицу
        table = soup.find("table")
        print(f"[DEBUG] Любая таблица найдена: {table is not None}")
    else:
        print(f"[DEBUG] Таблица tblgrades найдена!")
    
    if not table:
        return "❌ Таблица оценок не найдена"
    
    rows = table.find_all("tr")
    print(f"[DEBUG] Найдено строк в таблице: {len(rows)}")
    result = []
    
    months_ru = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
    }
    result.append(f"📊 *Оценки за {months_ru[month]} {year}*\n")
    
    for i, row in enumerate(rows[1:], 1):  # пропускаем строку с заголовками (числа месяца)
        cells = row.find_all("td")
        if not cells:
            continue
        
        # Название предмета — в div.table-button первой ячейки
        subject_div = cells[0].find("div", class_="table-button")
        if not subject_div:
            print(f"[DEBUG] Строка {i}: div.table-button не найден")
            # Попробуем просто взять текст из первой ячейки
            subject = cells[0].get_text(strip=True)
        else:
            subject = subject_div.get_text(strip=True)
        
        if not subject:
            continue
        
        print(f"[DEBUG] Строка {i}: предмет = {subject}")
        
        # Оценки — в остальных ячейках внутри <b>
        grades = []
        for cell in cells[1:]:
            b = cell.find("b")
            if b:
                text = b.get_text(strip=True)
                if text:
                    grades.append(text)
        
        print(f"[DEBUG] Строка {i}: оценки = {grades}")
        
        if grades:
            result.append(f"• *{subject}*: {', '.join(grades)}")
    
    print(f"[DEBUG] Всего предметов с оценками: {len(result) - 1}")
    
    return "\n".join(result) if len(result) > 1 else "📭 Оценок за этот месяц нет"
