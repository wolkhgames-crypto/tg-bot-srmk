import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://rmk.stavedu.ru:8010/moodle"
LOGIN_URL = "https://rmk.stavedu.ru:8010/moodle/login/index.php"
DIARY_URL = "https://rmk.stavedu.ru:8010/moodle/eioswork/diaries/studentsdiary.php"
TIMETABLE_URL = "https://rmk.stavedu.ru:8010/moodle/eioswork/timetable/watchstudent.php"
TIMETABLE_INDEX_URL = "https://rmk.stavedu.ru:8010/moodle/eioswork/timetable/index.php"

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
        
        # Оценки без смайликов
        grades = []
        attestation = None
        first_item_processed = False
        
        for cell in cells[1:]:
            b = cell.find("b")
            if b:
                text = b.get_text(strip=True)
                if text:
                    # Разбиваем строку на отдельные символы
                    for char in text:
                        if not first_item_processed:
                            # Первый элемент - аттестация
                            if char.isdigit():
                                attestation = char
                                try:
                                    grade_sum += int(char)
                                    total_grades += 1
                                except ValueError:
                                    pass
                            elif char.lower() == 'н':
                                attestation = 'н/а'
                            first_item_processed = True
                        else:
                            # Остальные - обычные оценки
                            if char.isdigit():
                                grades.append(char)
                                try:
                                    grade_sum += int(char)
                                    total_grades += 1
                                except ValueError:
                                    pass
                            elif char.lower() == 'н':
                                grades.append('н')
        
        if attestation or grades:
            subject_line = f"📚 *{subject}*\n"
            if attestation:
                subject_line += f"   Аттестация: `{attestation}`\n"
            if grades:
                subject_line += f"   Оценки: `{'|'.join(grades)}`\n"
            result.append(subject_line)
    
    # Добавляем статистику
    if total_grades > 0:
        avg = grade_sum / total_grades
        result.append(f"━━━━━━━━━━━━━━━━")
        result.append(f"📈 *Средний балл:* `{avg:.2f}`")
        result.append(f"📝 *Всего оценок:* `{total_grades}`")
    
    return "\n".join(result) if len(result) > 1 else "📭 Оценок за этот месяц нет"

async def get_all_groups(cookies: dict) -> dict:
    """Получает список всех групп и их ID"""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)

    try:
        async with aiohttp.ClientSession(connector=connector, cookies=cookies, timeout=timeout) as session:
            async with session.get(TIMETABLE_INDEX_URL) as resp:
                html = await resp.text()
        
        soup = BeautifulSoup(html, "html.parser")
        groups = {}
        
        # Ищем все ссылки на группы
        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            # Проверяем, что это ссылка на расписание группы
            if "watchstudent.php" in href and "group=" in href:
                # Извлекаем ID группы из URL
                import re
                # Ищем group=XXX в URL (учитываем &amp; и &)
                match = re.search(r'group=(\d+)', href)
                if match:
                    group_id = match.group(1)
                    group_name = link.get_text(strip=True).upper()
                    if group_name and len(group_name) <= 10:  # Фильтруем только короткие названия групп
                        groups[group_name] = group_id
        
        return groups
    except Exception as e:
        return {}

async def fetch_timetable(cookies: dict, group_id: str, year: int = None, month: int = None) -> str | None:
    """Получает и парсит расписание для группы"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month

    url = f"{TIMETABLE_URL}?year={year}&month={month}&group={group_id}"
    
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)

    try:
        async with aiohttp.ClientSession(connector=connector, cookies=cookies, timeout=timeout) as session:
            async with session.get(url) as resp:
                final_url = str(resp.url)
                html = await resp.text()

                if "login" in final_url or "403" in html:
                    return None

        return parse_timetable(html)
    except Exception as e:
        return "❌ Сервер недоступен. Попробуй позже."

def parse_timetable(html: str) -> str:
    """Парсит расписание из HTML"""
    soup = BeautifulSoup(html, "html.parser")
    
    # Ищем таблицу с расписанием
    table = soup.find("table")
    if not table:
        return "❌ Расписание не найдено"
    
    result = []
    result.append("📅 *Расписание занятий*\n")
    
    # Парсим расписание (структура зависит от HTML)
    # Это базовая версия, нужно будет доработать под реальную структуру
    rows = table.find_all("tr")
    
    current_day = None
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue
        
        # Здесь нужна логика парсинга в зависимости от структуры HTML
        # Пока возвращаем заглушку
        
    result.append("_Функция в разработке..._")
    return "\n".join(result)
