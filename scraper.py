import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://rmk.stavedu.ru:8010/moodle"
LOGIN_URL = "https://rmk.stavedu.ru:8010/moodle/login/index.php"
DIARY_URL = "https://rmk.stavedu.ru:8010/moodle/eioswork/diaries/studentsdiary.php"

async def get_login_token(session: aiohttp.ClientSession) -> str:
    """Moodle требует logintoken с формы"""
    try:
        async with session.get(LOGIN_URL, allow_redirects=True, max_redirects=5) as resp:
            html = await resp.text()
            
        soup = BeautifulSoup(html, "html.parser")
        token = soup.find("input", {"name": "logintoken"})
        
        if token:
            return token["value"]
        else:
            return ""
    except Exception as e:
        return ""

async def login(username: str, password: str) -> dict | None:
    """Возвращает куки если успешно, иначе None"""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            token = await get_login_token(session)

            data = {
                "anchor": "",
                "logintoken": token,
                "username": username,
                "password": password,
            }

            async with session.post(LOGIN_URL, data=data, allow_redirects=True) as resp:
                final_url = str(resp.url)

                # Успех — редиректнуло на /moodle/ а не обратно на login
                if "login" in final_url:
                    return None

                cookies = {}
                for name, cookie in session.cookie_jar.filter_cookies(LOGIN_URL).items():
                    cookies[name] = cookie.value
                return cookies if cookies else None
    except Exception as e:
        return None

async def fetch_grades(cookies: dict, year: int = None, month: int = None) -> str | None:
    """Получает и парсит оценки за месяц"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month

    url = f"{DIARY_URL}?year={year}&month={month}"
    
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)

    try:
        async with aiohttp.ClientSession(connector=connector, cookies=cookies, timeout=timeout) as session:
            async with session.get(url) as resp:
                final_url = str(resp.url)
                html = await resp.text()

                if "login" in final_url or "403" in html:
                    return None

        return parse_grades(html, year, month)
    except Exception as e:
        return "❌ Сервер недоступен. Попробуй позже."

def format_grade(grade: str) -> str:
    """Добавляет цветной индикатор к оценке"""
    try:
        grade_num = int(grade)
        if grade_num == 5:
            return f"🟢 {grade}"
        elif grade_num == 4:
            return f"🟡 {grade}"
        elif grade_num == 3:
            return f"🟠 {grade}"
        elif grade_num <= 2:
            return f"🔴 {grade}"
    except ValueError:
        pass
    return grade

def parse_grades(html: str, year: int, month: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    
    table = soup.find("table", id="tblgrades")
    if not table:
        table = soup.find("table")
    
    if not table:
        return "❌ Таблица оценок не найдена"
    
    rows = table.find_all("tr")
    result = []
    
    months_ru = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
    }
    result.append(f"📊 *Оценки за {months_ru[month]} {year}*\n")
    
    total_grades = 0
    grade_sum = 0
    
    for i, row in enumerate(rows[1:], 1):
        cells = row.find_all("td")
        if not cells:
            continue
        
        # Название предмета
        subject_div = cells[0].find("div", class_="table-button")
        if not subject_div:
            subject = cells[0].get_text(strip=True)
        else:
            subject = subject_div.get_text(strip=True)
        
        if not subject:
            continue
        
        # Оценки с цветными индикаторами
        grades = []
        for cell in cells[1:]:
            b = cell.find("b")
            if b:
                text = b.get_text(strip=True)
                if text:
                    formatted = format_grade(text)
                    grades.append(formatted)
                    try:
                        grade_sum += int(text)
                        total_grades += 1
                    except ValueError:
                        pass
        
        if grades:
            result.append(f"📚 *{subject}*\n   {' '.join(grades)}\n")
    
    # Добавляем статистику
    if total_grades > 0:
        avg = grade_sum / total_grades
        result.append(f"━━━━━━━━━━━━━━━━")
        result.append(f"📈 *Средний балл:* `{avg:.2f}`")
        result.append(f"📝 *Всего оценок:* `{total_grades}`")
    
    return "\n".join(result) if len(result) > 1 else "📭 Оценок за этот месяц нет"
