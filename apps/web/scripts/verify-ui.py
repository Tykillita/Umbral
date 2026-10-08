"""QA de interfaz contra API/snapshot reales en modo offline, sin consumir Gemini.

Desde la raíz: tests/.venv/Scripts/python.exe apps/web/scripts/verify-ui.py --url http://127.0.0.1:8011
PLAYWRIGHT_BROWSERS_PATH debe señalar tests/.browsers. Guarda capturas y JSON en apps/web/.qa.
La edición/revisión automatizada queda en la SQLite de QA, identificada como prueba, nunca como aprobación humana.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright



def choose_option(page, testid, value):
    """Menús desplegables propios (sin <select> nativo): abre la lista y pulsa la opción por su valor."""
    page.get_by_test_id(testid).click()
    page.locator(f'[role="listbox"] [role="option"][data-value="{value}"]').click()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8011')
    args = parser.parse_args()
    base = args.url.rstrip('/')
    if urlsplit(base).hostname not in {'127.0.0.1', 'localhost'}:
        raise RuntimeError('Esta prueba solo puede modificar una API local de QA.')
    output = Path(__file__).resolve().parents[1] / '.qa'
    output.mkdir(exist_ok=True)
    report: dict = {'startedAtUtc': datetime.now(timezone.utc).isoformat(), 'url': base,
                    'checks': [], 'layouts': [], 'pageErrors': [], 'externalRequests': []}

    def checked(label: str) -> None:
        report['checks'].append(label)

    def layout(page, view: str, width: int) -> None:
        metrics = page.evaluate('''({width:innerWidth, scroll:document.documentElement.scrollWidth,
          unlabeled:[...document.querySelectorAll('input,textarea,select')].filter(e=>
          !e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).length})''')
        report['layouts'].append({'view': view, **metrics})
        page.screenshot(path=str(output / f'{view}-{width}.png'))
        assert metrics['scroll'] <= width, f'Overflow en {view}/{width}: {metrics}'
        assert metrics['unlabeled'] == 0, f'Control sin etiqueta en {view}/{width}'

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(locale='es-PA', timezone_id='America/Panama')
            health = context.request.get(base + '/api/v1/health').json()
            assert health['offline'] and health['authMode'] == 'local', 'La API debe ser offline/auth local.'
            assert health['classifier'] == 'laya' and not health['containsFixtures'], 'Se exige snapshot real con Laya.'
            report['snapshotId'] = health['snapshotId']
            report['counts'] = health['counts']
            report['snapshotResponseSha256'] = hashlib.sha256(context.request.get(base + '/api/v1/snapshot').body()).hexdigest()
            checked('API real: snapshot sin fixtures, Laya y offline/auth local')

            def limit_network(route):
                if not route.request.url.startswith(base + '/'):
                    report['externalRequests'].append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', limit_network)
            page = context.new_page()
            page.on('pageerror', lambda e: report['pageErrors'].append(str(e)))
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base + '/')
                expect(page.get_by_role('link', name='Ver la agenda')).to_be_visible()
                layout(page, 'inicio', width)
                page.goto(base + '/app')
                expect(page.get_by_test_id('topic-card')).to_have_count(5, timeout=30000)
                warning_toggle = page.get_by_test_id('classification-warning-toggle')
                expect(warning_toggle).to_be_visible()
                warning_toggle.click()
                warning_dialog = page.get_by_test_id('classification-warning')
                expect(warning_dialog).to_be_visible()
                expect(warning_dialog).to_contain_text('Laya puede asignar categorías erróneas y sus porcentajes no son confianza editorial: revisa categoría e impacto antes de usar el ranking.')
                page.screenshot(path=str(output / f'classification-warning-{width}.png'))
                page.keyboard.press('Escape')
                expect(warning_dialog).to_have_count(0)
                expect(warning_toggle).to_be_focused()
                checked(f'Advertencia de Laya en modal: contenido completo, Escape y retorno de foco a {width}px')
                expect(page.get_by_test_id('mock-banner')).to_have_count(0)
                expect(page.get_by_test_id('fixture-notice')).to_have_count(0)
                page.evaluate('document.fonts.ready')
                if width == 1440:
                    report['fonts'] = page.evaluate("[...document.fonts].filter(f => f.status==='loaded').map(f=>({family:f.family,weight:f.weight,status:f.status}))")
                    assert any('Barlow Condensed' in f['family'] for f in report['fonts'])
                    assert any('Atkinson Hyperlegible' in f['family'] for f in report['fonts'])
                    page.wait_for_timeout(1500)  # deja terminar la animación de entrada de las viñetas antes de medir
                    boxes = page.get_by_test_id('topic-card').evaluate_all('(items)=>items.map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width}))')
                    assert boxes[0]['width'] > boxes[1]['width'] * 1.8, 'La primera viñeta debe abarcar las dos columnas.'
                    assert abs(boxes[1]['y'] - boxes[2]['y']) < 2, 'Las viñetas2/3 deben compartir fila.'
                    checked('Tipografías locales cargadas y composición cómic: primera viñeta dominante, siguientes en dos columnas')
                layout(page, 'agenda', width)
                topic = page.get_by_test_id('topic-card').first.get_attribute('data-topic-id')
                page.get_by_test_id('open-ficha').first.focus()
                page.keyboard.press('Enter')
                expect(page.get_by_test_id('ficha')).to_be_visible()
                expect(page.locator('#contenido')).to_be_focused()
                expect(page.get_by_test_id('source-item').first).to_be_visible()
                layout(page, 'ficha', width)
                page.get_by_test_id('go-drafts').click()
                expect(page.get_by_test_id('draft-generate')).to_be_visible()
                choose_option(page, 'draft-provider', 'plantilla')
                page.get_by_test_id('draft-generate').click()
                expect(page.get_by_test_id('draft-origin-label')).to_have_attribute('data-mode', 'plantilla', timeout=30000)
                expect(page.get_by_test_id('draft-validation')).to_have_attribute('data-ok', 'true')
                expect(page.get_by_test_id('draft-claim').first).to_be_visible()
                layout(page, 'borradores', width)
                page.get_by_test_id('nav-fuentes').focus(); page.keyboard.press('Enter')
                expect(page.get_by_test_id('sources-view')).to_be_visible()
                expect(page.get_by_test_id('sources-snapshot-id')).to_have_text(health['snapshotId'])
                expect(page.get_by_test_id('integrity-status')).to_contain_text('verificado')
                layout(page, 'fuentes', width)
                checked(f'4 vistas: API real, origen plantilla, teclado, etiquetas y sin overflow a {width}px')

                toggle = page.get_by_test_id('assistant-toggle')
                toggle.click()
                field = page.get_by_test_id('assistant-input')
                expect(field).to_be_focused()
                field.fill('Qué cinco temas merecen revisión para la agenda de Panamá')
                field.press('Enter')
                expect(page.get_by_test_id('assistant-answer')).to_have_count(1, timeout=30000)
                expect(page.get_by_test_id('assistant-citation').first).to_be_visible()
                expect(page.get_by_test_id('assistant-answer').first).not_to_have_attribute('data-status', 'abstencion')
                field.fill('Cuántos turistas visitaron Marte en 1850')
                expect(page.get_by_test_id('assistant-send')).to_be_enabled()
                field.press('Enter')
                expect(page.get_by_test_id('assistant-answer')).to_have_count(2, timeout=30000)
                expect(page.get_by_test_id('assistant-answer').last).to_have_attribute('data-status', 'abstencion')
                expect(page.get_by_test_id('assistant-missing').last).to_be_visible()
                field.fill('Consulta sin enviar')
                if width < 1024:
                    expect(page.get_by_role('dialog')).to_have_attribute('aria-modal', 'true')
                    page.get_by_test_id('assistant-send').focus(); page.keyboard.press('Tab')
                    expect(page.get_by_test_id('assistant-close')).to_be_focused()
                    page.keyboard.press('Shift+Tab'); expect(page.get_by_test_id('assistant-send')).to_be_focused()
                page.screenshot(path=str(output / f'assistant-{width}.png'))
                assert page.get_by_test_id('assistant-panel').evaluate('(e)=>e.scrollWidth <= e.clientWidth')
                field.press('Escape')
                expect(toggle).to_be_focused()
                checked(f'Asistente a {width}px: citas, abstención, faltantes, Tab móvil y retorno con Escape')

            # Una edición y transición de QA sobre SQLite propia, sin aprobación/publicación.
            page.goto(base + f'/app#/borradores/{topic}')
            expect(page.get_by_test_id('draft-brief')).to_be_visible()
            page.get_by_test_id('review-reviewer').fill('Automatización QA (no revisión editorial)')
            title = page.get_by_test_id('draft-title')
            title.fill(title.input_value().split(' [QA')[0][:130] + f' [QA-{datetime.now(timezone.utc):%H%M%S%f}]')
            page.get_by_test_id('draft-save').click()
            expect(page.get_by_test_id('draft-saved')).to_be_visible()
            status = page.get_by_test_id('review-status').get_attribute('data-status')
            if status == 'nuevo':
                page.get_by_test_id('review-action-en_revision').click()
                expect(page.get_by_test_id('review-status')).to_have_attribute('data-status', 'en_revision')
            page.get_by_test_id('export-markdown').click()
            expect(page.get_by_test_id('export-preview')).to_contain_text(health['snapshotId'])
            checked('Edición, guardar, transición en_revision de QA y exportación con snapshot correcto')

            # Pesos reales por sesión: guardar, invalidar agenda y rechazar una versión concurrente.
            page.get_by_test_id('nav-fuentes').click()
            expect(page.get_by_test_id('rules-editor')).to_be_visible()
            for key, value in {'R': 40, 'I': 15, 'U': 20, 'N': 15, 'E': 10}.items():
                page.get_by_test_id(f'rules-weight-{key}').fill(str(value))
            page.get_by_test_id('rules-author').fill('Automatización QA (no política editorial)')
            page.get_by_test_id('rules-reason').fill('Verificar cambio de pesos e invalidación de agenda en SQLite de QA')
            page.get_by_test_id('rules-save').click()
            expect(page.get_by_test_id('rules-saved')).to_be_visible()
            policy = context.request.get(base + '/api/v1/rules').json()
            expect(page.get_by_test_id('rules-version')).to_have_text(policy['rulesVersion'])
            page.get_by_test_id('nav-agenda').click()
            expect(page.get_by_test_id('topic-card')).to_have_count(5)
            expect(page.get_by_test_id('agenda-view')).to_contain_text(policy['formula'])
            expect(page.get_by_test_id('card-score-R').first).to_contain_text('R · 40')
            toggle = page.get_by_test_id('filters-toggle')
            if toggle.is_visible() and not page.get_by_test_id('filter-scope').is_visible():
                toggle.click()  # en móvil los filtros están plegados
            choose_option(page, 'filter-scope', 'all')
            expect(page.get_by_test_id('agenda-scope-note')).to_contain_text('Se incluyen temas fuera')
            choose_option(page, 'filter-scope', 'in_scope')
            page.get_by_test_id('nav-fuentes').click()
            expect(page.get_by_test_id('rules-editor')).to_be_visible()
            concurrent = context.request.put(base + '/api/v1/rules', data={
                'expectedVersion': policy['version'], 'weights': {'R': 39, 'I': 16, 'U': 20, 'N': 15, 'E': 10},
                'author': 'Segundo proceso QA', 'reason': 'Provocar conflicto de versión controlado'})
            assert concurrent.status == 200
            page.get_by_test_id('rules-reason').fill('Texto conservado ante conflicto')
            page.get_by_test_id('rules-save').click()
            expect(page.get_by_text('La política cambió mientras editabas')).to_be_visible()
            expect(page.get_by_test_id('rules-reason')).to_have_value('Texto conservado ante conflicto')
            page.get_by_role('button', name='Recargar política vigente').click()
            expect(page.get_by_test_id('rules-weight-R')).to_have_value('39')
            expect(page.get_by_text('La política cambió mientras editabas')).to_have_count(0)
            checked('Pesos guardados en SQLite real, agenda/formula/version refrescadas, alcance y conflicto409 sin sobrescritura')
            expect(page.get_by_test_id('local-connections')).to_contain_text('Modo sin conexión')
            expect(page.get_by_role('button', name='Preparar inicio de sesión')).to_be_disabled()
            checked('Conexión personal visible en localhost, operaciones de red desactivadas offline')
            page.emulate_media(reduced_motion='reduce')
            transition = page.get_by_test_id('rules-save').evaluate('(e)=>getComputedStyle(e).transitionDuration')
            assert max(float(x.strip().removesuffix('s')) for x in transition.split(',')) <= .001
            page.emulate_media(media='print')
            assert page.get_by_test_id('rules-editor-card').evaluate('(e)=>getComputedStyle(e).boxShadow') == 'none'
            page.emulate_media(media='screen', reduced_motion='no-preference')
            checked('Movimiento reducido respetado e impresión sin sombras')

            # Retener la respuesta de topics permite observar la carga, luego fallar de manera controlada.
            broken = context.new_page()
            blocked = []
            broken.route('**/api/v1/topics?*', lambda route: blocked.append(route))
            broken.goto(base + '/app')
            expect(broken.get_by_text('Cargando agenda…')).to_be_visible()
            assert blocked
            for route in blocked:
                route.fulfill(status=503, content_type='application/json', body='{"code":"qa_unavailable","message":"Fallo controlado de QA"}')
            broken.unroute('**/api/v1/topics?*')
            broken.route('**/api/v1/topics?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{"code":"qa_unavailable","message":"Fallo controlado de QA"}'))
            expect(broken.get_by_role('alert').last).to_contain_text('Fallo controlado de QA', timeout=30000)
            expect(broken.get_by_test_id('mock-banner')).to_have_count(0)
            broken.screenshot(path=str(output / 'agenda-error.png'))
            broken.unroute('**/api/v1/topics?*')
            broken.get_by_role('button', name='Reintentar').click()
            expect(broken.get_by_test_id('topic-card')).to_have_count(5)
            checked('Carga, error 503 visible sin mock y recuperación mediante Reintentar')
            assert not report['externalRequests'], 'El frontend local intentó salir a la red.'
            assert not report['pageErrors'], 'Errores JavaScript.'
            checked('Cero solicitudes externas del navegador y cero errores JavaScript')
            browser.close()
            report['passed'] = True
    except Exception as error:
        report['passed'] = False
        report['failure'] = str(error)
        raise
    finally:
        report['finishedAtUtc'] = datetime.now(timezone.utc).isoformat()
        (output / 'ui-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed': report.get('passed'), 'checks': len(report['checks']), 'report': str(output / 'ui-verification.json')}))


if __name__ == '__main__':
    main()
