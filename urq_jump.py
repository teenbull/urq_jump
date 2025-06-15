# coding: utf-8
import sublime, sublime_plugin, re, os

# Шаблон для создания новой локации с курсором на позиции |
LOC_TEMPLATE = """
:{} 
    pln | 
    end
"""

# Паттерны для поиска ссылок на локации в разных форматах:
# 1. [[link|text]] - викиссылка с текстом
# 2. [[link]] - простая викиссылка  
# 3. btn название - кнопка
# 4. goto/proc название - переход/процедура (останавливается перед else/&/;/*)
LINK_PATTERNS = [
    {'rx': re.compile(r'\[\[([^|\]]+)\|([^|\]]+)\]\]'), 'grp': 2},
    {'rx': re.compile(r'\[\[([^|\]]+)\]\]'), 'grp': 1},
    {'rx': re.compile(r'\bbtn\s+([^,;&\s]+(?:\s+[^,;&\s]+)*)'), 'grp': 1},
    {'rx': re.compile(r'\b(?:goto|proc)\s+([^;&/*]+?)(?=\s+else\b|\s*[;&]|\s*/\*|$)'), 'grp': 1},  # Фикс: захват до else/&/;/*
]

# Проверяет валидность выделенного текста для использования как имя локации
def _valid_sel(txt): 
    if not txt: return False
    t = txt.strip()
    if not t or ':' in t or '&' in t or '/*' in t: return False
    return True

# Проверяет что текст не является системным словом/оператором
def _valid_word(txt):
    if not txt: return False
    t = txt.strip().lower()
    # Системные операторы и ключевые слова
    keywords = {'and', 'or', 'if', 'else', 'then', 'btn', 'pln', 'end', 'goto', 'proc', 'act'}
    if t in keywords: return False
    # Математические и логические операторы
    if t in {'*', '+', '-', '/', '\\', '|', '<', '>', '=', '<>', '==', '!=', '<=', '>='}: return False
    # Скобки и знаки препинания
    if t in {'(', ')', '[', ']', '{', '}', ',', '.', ';', ':', '?', '!'}: return False
    # Проверка на $ как часть переменной
    if t == '$': return False
    return True

# Проверяет наличие переменных в тексте (шаблоны типа #var$, ##var$, #%var$)
def _has_vars(txt): return bool(re.search(r'#[#%]?[^$]*\$', txt))

# Очищает строку от комментариев и разбивает по & и ;
# Возвращает часть строки где находится курсор и скорректированную позицию
def clean_line(ln, pos):
    ln = re.sub(r'/\*.*?\*/', '', ln); sc = ln.find(';')  # Убираем /* комменты */ и находим ;
    if sc >= 0 and pos > sc: return "", pos  # Если курсор после ; - пустая строка
    if sc >= 0: ln = ln[:sc]  # Обрезаем по ;
    
    # Разбиваем по & и находим нужную часть
    p = 0
    for part in ln.split('&'):
        pe = p + len(part)
        if p <= pos < pe: return part, pos - p  # Возвращаем часть где курсор
        p = pe + 1
    return ln, pos

# Ищет ближайшую ссылку к позиции курсора в тексте
def find_link(txt, pos):
    best, dist = None, float('inf')
    for cfg in LINK_PATTERNS:
        for m in cfg['rx'].finditer(txt):  # Ищем все совпадения для каждого паттерна
            try:
                link = m.group(cfg['grp']).strip()  # Извлекаем имя ссылки
                if not _valid_sel(link): continue  # Пропускаем невалидные
                ls, le = m.start(cfg['grp']), m.end(cfg['grp'])  # Границы ссылки
                # Расчет расстояния от курсора до ссылки
                d = 0 if ls <= pos <= le else min(abs(pos - ls), abs(pos - le))
                # Выбираем ближайшую, при равном расстоянии - более короткую
                if d < dist or (d == dist and (not best or len(link) < len(best))):
                    best, dist = link, d
            except: pass
    return best

# Получает текст для перехода: выделение -> ссылка на строке -> слово под курсором
def get_sel(v, pt):
    sel = v.sel()
    # Если есть выделение и оно валидно - используем его (любое выделение разрешено)
    if sel and not sel[0].empty():
        txt = v.substr(sel[0]).strip()
        if _valid_sel(txt): return txt
    
    # Ищем ссылку на текущей строке рядом с курсором
    lr = v.line(pt); ln = v.substr(lr); pos = pt - lr.begin()
    clean, cpos = clean_line(ln, pos)  # Очищаем строку
    if clean:
        link = find_link(clean, cpos)  # Ищем ссылку
        if link: return link
    
    # Последний шанс - слово под курсором (с проверкой на системные слова)
    # wr = v.word(pt)
    # if wr and not wr.empty():
    #     txt = v.substr(wr).strip()
    #     if _valid_sel(txt) and _valid_word(txt): return txt  # Дополнительная проверка на системные слова
    return None

# Показывает сообщение в статусбаре с количеством локаций
def msg(txt, v): sublime.status_message(f"{txt}. Locs: {len(v.find_all(':', 0))}")

class UrqJumpCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        v = self.view
        if not v.sel(): return
        
        # Получаем текст для поиска/создания локации
        txt = get_sel(v, v.sel()[0].begin())
        if not txt: msg("Нет текста", v); return
        if _has_vars(txt): msg(f"Есть переменные: {txt}", v); return
        
        # Поиск существующей локации
        norm = txt.strip().lower()
        for reg in v.find_all(":", 0):  # Ищем все двоеточия
            line = v.substr(v.line(reg)).strip()
            if line.startswith(':') and '&' not in line:  # Проверяем что это локация
                loc = line[1:].split(';')[0].strip().lower()  # убираем коммент после :
                if loc == norm:  # Нашли совпадение
                    v.sel().clear(); v.sel().add(reg)  # Переходим к локации
                    v.show_at_center(reg); msg(f"→ {loc}", v)
                    return
        
        # Создание новой локации если не найдена
        cur = v.sel()[0].begin(); ins_pos = v.size()  # По умолчанию в конец файла
        
        # Ищем ближайший end после курсора для вставки перед ним
        text_after = v.substr(sublime.Region(cur, v.size()))
        end_match = re.search(r'^\s*end\s*(?:;.*)?$', text_after, re.M)  # end + опциональный коммент
        if end_match:
            ins_pos = cur + end_match.end()  # Позиция после end
            if ins_pos < v.size() and v.substr(ins_pos) != '\n': ins_pos += 1  # Добавляем \n если нужно
        
        # Проверяем нужен ли перенос строки перед вставкой
        need_newline = ins_pos > 0 and v.substr(ins_pos - 1) != '\n'
        prefix = '\n' if need_newline else ''
        
        # Вставляем шаблон новой локации
        tmpl = prefix + LOC_TEMPLATE.format(txt)
        cursor_offset = tmpl.find('|')  # Находим позицию курсора в шаблоне
        if cursor_offset != -1:
            tmpl = tmpl.replace('|', '')  # Убираем маркер курсора
            v.insert(edit, ins_pos, tmpl)  # Вставляем текст
            v.sel().clear(); v.sel().add(ins_pos + cursor_offset)  # Ставим курсор
            v.show_at_center(ins_pos + cursor_offset)
        else:
            v.insert(edit, ins_pos, tmpl)
        
        msg(f"✓ {txt}", v)
    
    # Команда активна только для .qst и .txt файлов
    def is_enabled(self): 
        file_name = self.view.file_name()
        return file_name and file_name.lower().endswith(('.qst', '.txt'))        
        # return "urql" in os.path.basename(self.view.settings().get('syntax', '')).lower()

    def description(self): return "URQ Jump/Create Location"