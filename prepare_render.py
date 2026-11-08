"""Restore the bundled UI and apply the maintainable Rakovar storefront overlay."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "RAKOVAR_full_project_MAX_preview.zip"
REQUIRED = {"storefront.html", "admin_login.html", "admin.html"}
ALLOWED_DIRS = {"templates", "static", "assets"}

BRAND_LOGO = "https://scdn.chibbis.ru/live/logos/ef70804ad82b43394b885f18187aa24c.png"
BRAND_BANNER = "https://scdn.chibbis.ru/live/banners/df9c6ef11fd698f6963dbb540a41dc1f.png"
PHOTO_CRAYFISH = "https://scdn.chibbis.ru/live/products/108f3eeaa45bb0138f55295849aa2f7e.jpeg"
PHOTO_SET = "https://scdn.chibbis.ru/live/products/fe4c4a6a9dc1e91b6eee1127139e5bae.jpeg"
PHOTO_SHRIMP = "https://scdn.chibbis.ru/live/products/5bf788161e3f482151c9e6ec7b625522.jpeg"
PHOTO_GIFT = "https://scdn.chibbis.ru/live/products/685af54568bd400c7f80eba0b88c2303.jpeg"

HERO_AND_TRUST = f"""
    <section class="hero wrap">
      <div class="hero-copy">
        <div class="eyebrow"><span></span>ЯРОСЛАВЛЬ · МОРСКИЕ И РЕЧНЫЕ ДЕЛИКАТЕСЫ</div>
        <h1 id="heroTitle">Море ближе,<br><em>чем кажется.</em></h1>
        <p id="heroText">Живые и варёные раки, крабы, креветки, мидии, рыба, авторские сеты и съедобные подарки. Подберём деликатесы для вечера, праздника и особого повода.</p>
        <div class="hero-actions"><a class="btn btn-primary" href="#catalog"><span id="heroCta">Смотреть меню</span><span>↗</span></a><a class="btn btn-ghost" href="#sets">Собрать свой сет</a></div>
        <div class="hero-notes"><span>✦ Готовим по заказу</span><span>✦ Подарочные композиции</span><span>✦ Розничный магазин</span></div>
      </div>
      <div class="hero-visual"><img src="{BRAND_BANNER}" alt="РАКОВАРЪ — морские деликатесы и блюда бренда"/><div class="hero-photo-caption"><span>МОРЕ В КАЖДОЙ ДЕТАЛИ</span><b>РАКОВАРЪ</b></div><div class="hero-card"><span class="tiny-label">ДЛЯ ВАШЕГО ПОВОДА</span><strong>Соберите<br>свой сет</strong><a href="#sets">Выбрать состав ↗</a></div></div>
    </section>
    <section class="trust-strip"><div class="wrap trust-inner"><span><b>9+ лет</b> в морской гастрономии*</span><span><b>20+</b> вариантов сетов*</span><span><b>30+</b> моделей подарочных композиций*</span><span><b>По заказу</b> индивидуальная подготовка</span></div><div class="trust-footnote">*Показатели из публичного описания бренда; актуальность формулировок подтверждается компанией.</div></section>
    <section class="category-showcase wrap" aria-label="Популярные категории"><div class="category-showcase-head"><div><div class="eyebrow">ВЫБЕРИТЕ, ЧТО БУДЕТ НА СТОЛЕ</div><h2>От любимых раков <em>до подарочного сета</em></h2></div><a href="#catalog" class="text-link">Весь каталог ↗</a></div><div class="category-showcase-grid">
      <button class="category-tile" data-category-select="Раки"><img src="{PHOTO_CRAYFISH}" alt="Варёные раки"/><span><small>РЕЧНАЯ КЛАССИКА</small><b>Раки</b><i>Смотреть ↗</i></span></button>
      <button class="category-tile" data-category-select="Креветки"><img src="{PHOTO_SHRIMP}" alt="Креветки"/><span><small>МОРСКОЙ ХИТ</small><b>Креветки</b><i>Смотреть ↗</i></span></button>
      <button class="category-tile" data-category-select="Сеты"><img src="{PHOTO_SET}" alt="Сет морепродуктов"/><span><small>ДЛЯ КОМПАНИИ</small><b>Сеты и ассорти</b><i>Смотреть ↗</i></span></button>
      <button class="category-tile" data-category-select="Подарки"><img src="{PHOTO_GIFT}" alt="Подарочный сет"/><span><small>СЪЕДОБНЫЕ ЭМОЦИИ</small><b>Букеты и подарки</b><i>Смотреть ↗</i></span></button>
    </div></section>
"""

def patch_storefront(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    html = html.replace(
        'Демонстрационная цифровая платформа РАКОВАРЪ — каталог, подарочные наборы и игровая зона.',
        'РАКОВАРЪ — морские и речные деликатесы в Ярославле. Раки, креветки, крабы, морские сеты и съедобные подарки.',
    )
    html = html.replace("РАКОВАРЪ — гастрономическая платформа", "РАКОВАРЪ — морские и речные деликатесы в Ярославле")
    html = html.replace("Каталог, подарочные наборы, клуб и конкурсы.", "Раки, креветки, крабы, мидии, авторские сеты и подарочные композиции.")
    html = html.replace(
        "ПРЕДПРОСМОТР РАКОВАРЪ · цены и наличие из публичного меню требуют подтверждения · оплата отключена",
        "ПРЕДПРОСМОТР · цены и наличие требуют подтверждения · фотографии из публичного меню · оплата отключена",
    )
    html = html.replace("images/rakovar_mark.svg", BRAND_LOGO)
    pattern = r'<section class="hero wrap">.*?</section>\s*<section class="trust-strip">.*?</section>'
    html, count = re.subn(pattern, HERO_AND_TRUST, html, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Could not replace original hero/trust sections")
    if 'class="category-showcase wrap"' not in html:
        raise RuntimeError("Category showcase was not inserted")
    html = html.replace(
        '<div class="eyebrow">ГАСТРОНОМИЧЕСКАЯ ВИТРИНА</div><h2>Выберите <em>своё</em></h2><p>Каталог собран по публичному меню РАКОВАРЪ. Цены, вес, состав и наличие ожидают подтверждения команды.</p>',
        '<div class="eyebrow">МЕНЮ РАКОВАРЪ</div><h2>Выберите <em>своё</em></h2><p>Позиции собраны из публичного меню и публикаций бренда. Цены, вес, состав и наличие предварительные — подтвердим перед заказом. Фотографии — из публичных карточек меню, до запуска их необходимо согласовать с компанией.</p>',
    )
    html = html.replace(
        '<div class="eyebrow">ЦИФРОВОЙ ПРОЕКТ</div><h2>Сервис, который<br><em>растёт вместе с брендом.</em></h2>',
        '<div class="eyebrow">О РАКОВАРЪ</div><h2>Морепродукты —<br><em>с характером.</em></h2>',
    )
    html = html.replace("Публичная карточка · подтвердить перед запуском", "Адрес магазина по публичному описанию бренда")
    html = html.replace(
        "<small>{{ site_settings.get('contact_hours','') }}</small>",
        "<small>{{ site_settings.get('contact_hours','') }}</small><small>Точку самовывоза и тариф доставки уточняйте у менеджера.</small>",
    )
    html = html.replace("концепция цифровой платформы", "морские и речные деликатесы · Ярославль")
    if "brand-refresh.css" not in html:
        html = html.replace(
            '<link rel="stylesheet" href="{{ url_for(\\'static\\', filename=\\'app.css\\') }}">',
            '<link rel="stylesheet" href="{{ url_for(\\'static\\', filename=\\'app.css\\') }}"><link rel="stylesheet" href="{{ url_for(\\'static\\', filename=\\'brand-refresh.css\\') }}">',
        )
    path.write_text(html, encoding="utf-8")

def patch_storefront_js(path: Path) -> None:
    js = path.read_text(encoding="utf-8")
    marker = "$$('#categories [data-category]').forEach(btn => btn.addEventListener('click', () => { state.category = btn.dataset.category; renderCategories(); renderProducts(); }));"
    addition = marker + "\n    $$('[data-category-select]').forEach(btn => btn.addEventListener('click', () => { state.category = btn.dataset.categorySelect; renderCategories(); renderProducts(); document.querySelector('#catalog').scrollIntoView({ behavior: 'smooth', block: 'start' }); }));"
    if "data-category-select" not in js:
        if marker not in js:
            raise RuntimeError("Could not find category click handler in storefront.js")
        js = js.replace(marker, addition)
    path.write_text(js, encoding="utf-8")

def main() -> int:
    if not ARCHIVE.is_file() or not zipfile.is_zipfile(ARCHIVE):
        print(f"ERROR: required project archive is missing or invalid: {ARCHIVE.name}", file=sys.stderr)
        return 2

    extracted: list[str] = []
    template_candidates: dict[str, list[zipfile.ZipInfo]] = {}
    with zipfile.ZipFile(ARCHIVE) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            parts = PurePosixPath(raw).parts
            if not parts or raw.startswith("/") or ".." in parts:
                continue
            indexes = [i for i, part in enumerate(parts) if part in ALLOWED_DIRS]
            if not indexes:
                continue
            index = indexes[0]
            folder = parts[index]
            relative = PurePosixPath(*parts[index + 1:])
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                continue
            if folder == "templates":
                template_candidates.setdefault(relative.name, []).append(info)
            destination = (ROOT / folder / Path(*relative.parts)).resolve()
            if ROOT not in destination.parents:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                output.write(source.read())
            extracted.append(f"{folder}/{relative.as_posix()}")

        for filename in REQUIRED:
            candidates = template_candidates.get(filename, [])
            if candidates:
                info = candidates[0]
                destination = ROOT / "templates" / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    output.write(source.read())

    missing = [name for name in REQUIRED if not (ROOT / "templates" / name).is_file()]
    if missing:
        print("ERROR: required Flask templates absent from archive: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 3

    css_overlay = ROOT / "static" / "brand-refresh.css"
    if not css_overlay.is_file():
        print("ERROR: static/brand-refresh.css is missing from repository", file=sys.stderr)
        return 4
    patch_storefront(ROOT / "templates" / "storefront.html")
    patch_storefront_js(ROOT / "static" / "storefront.js")
    print(f"Restored {len(extracted)} UI files; applied Rakovar brand refresh.", flush=True)
    print("Verified Flask templates, brand stylesheet and category navigation.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
