"""搜索线索 → 管理员审核 → MySQL 商品 → 可重试的 Chroma 索引。"""
import asyncio
import hashlib
import json
import re
import unicodedata
from time import perf_counter
from sqlalchemy import select, update, func, or_
from sqlalchemy.exc import IntegrityError
from app.db.models import ProductUpdate, Product, WebEvidence, now
from app.db.mysql import database
from app.errors import AppError
from app.ingestion.converter import convert_page
from app.ingestion.sources import fetch_product_page, official_source
from app.ingestion.service import index_lock, index_product, content_hash
from app.products.schemas import ProductInput, utc
from app.products.matching import canonical, BRAND_ALIASES

EDITABLE = ('pending', 'draft', 'extract_failed')
STATUSES = (*EDITABLE, 'processing', 'index_pending', 'succeeded', 'rejected')


def normalized(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', value).casefold())


def identity(product):
    brand = canonical(product['brand'])
    model = unicodedata.normalize('NFKC', product['model']).casefold()
    for alias, replacement in BRAND_ALIASES.items():
        model = model.replace(alias, replacement)
    model = normalized(model)
    if model.startswith(brand):
        model = model[len(brand):]
    return [product['category_code'], brand, model]


def stable_product_id(product):
    return 'web-' + content_hash(identity(product))[:40]


def event(row, kind, actor=None, **details):
    row.events = [*row.events, {'at': now().isoformat() + 'Z', 'type': kind, 'actor': actor, **details}][-50:]


async def enqueue(db, evidence):
    """仅保存公开资料；同一 URL 和内容跨用户去重，不调用模型。"""
    from app.web_search.service import upsert
    count = 0
    for source in evidence:
        key = hashlib.sha256((source.url + '\n' + source.content_hash).encode()).hexdigest()
        if await db.get(ProductUpdate, key):
            continue
        values = {'id': key, 'source_url': source.url, 'title': source.title,
                  'source_content': source.content, 'source_hash': source.content_hash,
                  'category': source.category, 'captured_at': source.fetched_at,
                  'status': 'pending', 'version': 0, 'page_text': '', 'draft': {},
                  'field_evidence': {}, 'warnings': [], 'events': [], 'timings': {},
                  'review_note': '', 'updated_at': now()}
        # 冲突时保持已经审核的状态；不能重新打开已拒绝或已入库记录。
        await upsert(db, ProductUpdate, values, {'id': key})
        count += 1
    return count


async def sync_history():
    total = 0
    after = ''
    while True:
        async with database.session() as db:
            sources = (await db.scalars(select(WebEvidence).where(WebEvidence.id > after)
                                      .order_by(WebEvidence.id).limit(200))).all()
            if not sources:
                break
            total += await enqueue(db, sources)
            await db.commit()
            after = sources[-1].id
    return {'added_count': total}


def snapshot(row):
    if row is None:
        return None
    return {key: getattr(row, key) for key in ('id', 'category_code', 'brand', 'model', 'name',
            'summary', 'specs', 'status', 'source', 'source_url')} | {
                'source_updated_at': row.source_updated_at.isoformat() + 'Z'}


async def matching_product(db, draft):
    rows = (await db.scalars(select(Product).where(Product.category_code == draft['category_code']))).all()
    found = [row for row in rows if identity(snapshot(row)) == identity(draft)]
    if len(found) > 1:
        raise AppError(409, 'DUPLICATE_PRODUCT_IDENTITY', '本地存在多个相同型号与配置，请先合并重复商品')
    return found[0] if found else None


def plan(draft, proofs, existing):
    before = snapshot(existing)
    additions, conflicts = [], []
    if before:
        for key, value in draft['specs'].items():
            old = before['specs'].get(key)
            change = {'field': 'specs.' + key, 'old': old, 'new': value,
                      'evidence': proofs.get('specs.' + key, '')}
            if old is None or old == '':
                additions.append(change)
            elif old != value:
                conflicts.append(change)
        if not before['summary']:
            additions.append({'field': 'summary', 'old': before['summary'], 'new': draft['summary']})
        if before['status'] == 'discontinued':
            conflicts.append({'field': 'status', 'old': 'discontinued', 'new': 'active'})
    return {'mode': 'insert' if before is None else ('fill' if additions else 'existing'),
            'existing_product': before, 'target_hash': content_hash(before),
            'additions': additions, 'conflicts': conflicts}


def summary(row):
    return {'id': row.id, 'title': row.title, 'source_url': row.source_url,
            'category': row.category, 'status': row.status, 'version': row.version,
            'captured_at': row.captured_at.isoformat() + 'Z',
            'updated_at': row.updated_at.isoformat() + 'Z', 'product_id': row.product_id,
            'product_name': row.draft.get('name'), 'error_message': row.error_message}


async def get_row(db, id):
    row = await db.get(ProductUpdate, id)
    if row is None:
        raise AppError(404, 'UPDATE_NOT_FOUND', '商品更新记录不存在')
    return row


async def detail(id):
    async with database.session() as db:
        row = await get_row(db, id)
        preview = plan(row.draft, row.field_evidence, await matching_product(db, row.draft)) if row.draft else None
        return {**summary(row), 'source_content': row.source_content, 'page_url': row.page_url,
                'page_text': row.page_text, 'draft': row.draft, 'field_evidence': row.field_evidence,
                'warnings': row.warnings, 'events': row.events, 'timings': row.timings,
                'review_note': row.review_note, 'error_code': row.error_code, 'preview': preview}


async def list_records(status, query, page, limit):
    async with database.session() as db:
        statement = select(ProductUpdate)
        if status:
            statement = statement.where(ProductUpdate.status == status)
        if query:
            statement = statement.where(or_(ProductUpdate.title.contains(query, autoescape=True),
                                             ProductUpdate.source_url.contains(query, autoescape=True)))
        total = await db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (await db.scalars(statement.order_by(ProductUpdate.created_at.desc(), ProductUpdate.id)
                                 .offset((page - 1) * limit).limit(limit))).all()
        counts = (await db.execute(select(ProductUpdate.status, func.count()).group_by(ProductUpdate.status))).all()
    return {'items': [summary(row) for row in rows], 'total': total, 'page': page,
            'counts': dict(counts)}


def require_version(row, version, statuses=EDITABLE):
    if row.version != version:
        raise AppError(409, 'UPDATE_CHANGED', '记录已变化，请刷新后再操作')
    if row.status not in statuses:
        raise AppError(409, 'UPDATE_BUSY', '当前状态不允许此操作，请刷新记录')


def validate_draft(product, proofs, page, page_url, captured_at):
    """管理员编辑后仍核对原文、来源与格式，价格使用单独的快照导入流程。"""
    url, brand = official_source(page_url)
    values = product.model_dump(mode='json')
    if values['brand'] != brand or str(product.source_url) != url:
        raise AppError(422, 'SOURCE_CHANGED', '品牌与来源必须对应本次提取的官网页面')
    model_quote = proofs.get('model', '').strip()
    if not model_quote or model_quote not in page or values['model'].casefold() not in model_quote.casefold():
        raise AppError(422, 'MODEL_EVIDENCE_MISSING', '型号必须在提供的官网原文中逐字核对')
    if not values['specs']:
        raise AppError(422, 'SPECS_REQUIRED', '至少需要一项有原文依据的规格才能入库')
    accepted = {'model': model_quote}
    for key, value in values['specs'].items():
        quote = proofs.get('specs.' + key, '').strip()
        if not quote or quote not in page:
            raise AppError(422, 'SPEC_EVIDENCE_MISSING', f'{key} 缺少可核对的官网原文')
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            numbers = [float(n.replace(',', '')) for n in re.findall(r'\d[\d,]*(?:\.\d+)?', quote)]
            if float(value) not in numbers:
                raise AppError(422, 'SPEC_EVIDENCE_MISMATCH', f'{key} 的数值与原文不一致，暂不支持单位换算')
        elif isinstance(value, str) and value.casefold() not in quote.casefold():
            raise AppError(422, 'SPEC_EVIDENCE_MISMATCH', f'{key} 的字符值与原文不一致')
        if key in {'storage_gb', 'ram_gb', 'weight_g', 'screen_inches'} and ('|' in quote or ' / ' in quote):
            raise AppError(422, 'AMBIGUOUS_VARIANT', f'{key} 的原文包含多种配置，请提供具体配置的依据')
        accepted['specs.' + key] = quote
    summary_quote = proofs.get('summary', '')
    if summary_quote and summary_quote in page and values['summary'] == summary_quote:
        accepted['summary'] = summary_quote
    else:
        values['summary'] = f"{values['name']}，资料来源于品牌官网。"
    values.update(id=stable_product_id(values), status='draft', source=f'{brand} 官网',
                  source_updated_at=captured_at, source_url=url)
    checked = ProductInput.model_validate(values)
    utc(checked.source_updated_at)
    return checked.model_dump(mode='json'), accepted


async def prepare(id, version, url, actor):
    started = perf_counter()
    async with database.session() as db:
        row = await get_row(db, id)
        require_version(row, version)
        chosen_url, brand = official_source(url or row.page_url or row.source_url)
        claimed = await db.execute(update(ProductUpdate).where(ProductUpdate.id == id,
                      ProductUpdate.version == version, ProductUpdate.status.in_(EDITABLE))
                      .values(status='processing', version=version + 1, page_url=chosen_url,
                              error_code=None, error_message=None, updated_at=now()))
        if claimed.rowcount != 1:
            raise AppError(409, 'UPDATE_CHANGED', '记录已变化，请刷新')
        await db.refresh(row)
        event(row, 'extraction_started', actor, url=chosen_url)
        await db.commit()
    timings = {}
    try:
        mark = perf_counter()
        page = await fetch_product_page(chosen_url)
        timings['page_ms'] = round((perf_counter() - mark) * 1000, 2)
        mark = perf_counter()
        converted = await asyncio.wait_for(convert_page(page, brand), timeout=55)
        timings['structure_ms'] = round((perf_counter() - mark) * 1000, 2)
        draft, proofs = validate_draft(ProductInput.model_validate(converted['product']),
                            converted['field_evidence'], converted['page_text'], chosen_url, page['captured_at'])
        async with database.session() as db:
            row = await get_row(db, id)
            require_version(row, version + 1, ('processing',))
            row.page_url, row.page_text = chosen_url, converted['page_text']
            row.draft, row.field_evidence = draft, proofs
            row.warnings, row.status = converted['warnings'], 'draft'
            row.version += 1
            timings['extract_total_ms'] = round((perf_counter() - started) * 1000, 2)
            row.timings = {**row.timings, **timings}
            event(row, 'draft_created', actor, product=draft, field_evidence=proofs)
            await db.commit()
    except (Exception, asyncio.CancelledError) as exc:
        async with database.session() as db:
            row = await get_row(db, id)
            if row.status == 'processing' and row.version == version + 1:
                row.status, row.version = 'extract_failed', row.version + 1
                row.error_code = exc.code if isinstance(exc, AppError) else 'EXTRACTION_FAILED'
                row.error_message = exc.message if isinstance(exc, AppError) else '提取中断或失败，可重试；没有写入正式商品'
                row.timings = {**row.timings, **timings, 'extract_total_ms': round((perf_counter() - started) * 1000, 2)}
                event(row, 'extraction_failed', actor, code=row.error_code)
                await db.commit()
        if isinstance(exc, asyncio.CancelledError):
            raise
    return await detail(id)


async def save_draft(id, version, product, proofs, actor):
    async with database.session() as db:
        row = await get_row(db, id)
        require_version(row, version, ('draft',))
        checked, accepted = validate_draft(product, proofs, row.page_text, row.page_url, row.draft['source_updated_at'])
        claimed = await db.execute(update(ProductUpdate).where(ProductUpdate.id == id, ProductUpdate.version == version)
                                  .values(version=version + 1, updated_at=now()))
        if claimed.rowcount != 1:
            raise AppError(409, 'UPDATE_CHANGED', '记录已变化，请刷新')
        before = row.draft
        row.draft, row.field_evidence = checked, accepted
        event(row, 'draft_edited', actor, before=before, after=checked, field_evidence=accepted)
        await db.commit()
    return await detail(id)


async def finish_index(id):
    """调用方已持有 index_lock；SQL 已提交，失败保留可重试记录。"""
    started = perf_counter()
    async with database.session() as db:
        row = await get_row(db, id)
        product = await db.get(Product, row.product_id)
    try:
        if product is None:
            raise ValueError('missing product')
        await index_product(product)
        status, code, message = 'succeeded', None, None
    except Exception:
        status, code, message = 'index_pending', 'INDEX_PENDING', 'MySQL 商品已保存；Chroma 更新失败，请点击重试索引'
    async with database.session() as db:
        row = await get_row(db, id)
        row.status, row.error_code, row.error_message = status, code, message
        row.version += 1
        row.timings = {**row.timings, 'index_ms': round((perf_counter() - started) * 1000, 2)}
        event(row, 'indexed' if status == 'succeeded' else 'index_failed', code=code)
        await db.commit()


async def approve(id, version, target_hash, replacements, actor):
    async with index_lock:
        async with database.session() as db:
            row = await get_row(db, id)
            if row.status in ('succeeded', 'index_pending'):
                return await detail(id)
            require_version(row, version, ('draft',))
            draft, proofs = validate_draft(ProductInput.model_validate(row.draft), row.field_evidence,
                                          row.page_text, row.page_url, row.draft['source_updated_at'])
            product = await matching_product(db, draft)
            preview = plan(draft, proofs, product)
            if target_hash != preview['target_hash']:
                raise AppError(409, 'PRODUCT_CHANGED', '正式商品已更新，请刷新差异后重新确认')
            if set(replacements) - {c['field'] for c in preview['conflicts']}:
                raise AppError(422, 'INVALID_REPLACEMENT', '只能替换本次预览中明确列出的冲突字段')
            if product and product.status == 'discontinued' and 'status' not in replacements:
                raise AppError(422, 'DISCONTINUED_PRODUCT', '该商品已停用；需要明确勾选重新启用')
            started = perf_counter()
            before = snapshot(product)
            if product is None:
                values = dict(draft)
                values.update(status='active', source_updated_at=utc(ProductInput.model_validate(draft).source_updated_at))
                values['content_hash'] = content_hash(values)
                product = Product(**values)
                db.add(product)
            else:
                changes = {c['field']: c['new'] for c in preview['additions']}
                changes.update({c['field']: c['new'] for c in preview['conflicts'] if c['field'] in replacements})
                specs = dict(product.specs)
                for field, value in changes.items():
                    if field.startswith('specs.'):
                        specs[field[6:]] = value
                    else:
                        setattr(product, field, value)
                product.specs, product.status = specs, 'active'
                if changes or before['status'] != 'active':
                    product.source, product.source_url = draft['source'], draft['source_url']
                    product.source_updated_at = utc(ProductInput.model_validate(draft).source_updated_at)
                    product.content_hash = content_hash(snapshot(product))
            claimed = await db.execute(update(ProductUpdate).where(ProductUpdate.id == id,
                         ProductUpdate.version == version, ProductUpdate.status == 'draft')
                         .values(status='index_pending', version=version + 1, updated_at=now()))
            if claimed.rowcount != 1:
                raise AppError(409, 'UPDATE_CHANGED', '记录已变化，请刷新')
            row.product_id, row.reviewed_by, row.reviewed_at = product.id, actor, now()
            row.error_code, row.error_message = 'INDEX_PENDING', 'MySQL 商品已保存；检索索引尚未完成，可点击重试索引'
            event(row, 'mysql_committed', actor, before=before, after=snapshot(product),
                  replaced_fields=replacements, field_evidence=proofs)
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise AppError(409, 'PRODUCT_IDENTITY_CONFLICT', '商品身份已存在或发生变化，请刷新后重试') from exc
            row.timings = {**row.timings, 'mysql_ms': round((perf_counter() - started) * 1000, 2)}
            await db.commit()
        await finish_index(id)
    return await detail(id)


async def retry_index(id, version):
    async with index_lock:
        async with database.session() as db:
            row = await get_row(db, id)
            require_version(row, version, ('index_pending',))
        await finish_index(id)
    return await detail(id)


async def reject(id, version, note, actor):
    async with database.session() as db:
        row = await get_row(db, id)
        require_version(row, version)
        claimed = await db.execute(update(ProductUpdate).where(ProductUpdate.id == id,
                     ProductUpdate.version == version, ProductUpdate.status.in_(EDITABLE))
                     .values(status='rejected', version=version + 1, updated_at=now()))
        if claimed.rowcount != 1:
            raise AppError(409, 'UPDATE_CHANGED', '记录已变化，请刷新')
        row.reviewed_by, row.reviewed_at, row.review_note = actor, now(), note
        event(row, 'rejected', actor, note=note)
        await db.commit()
    return await detail(id)


async def recover_interrupted(db):
    # 单实例启动恢复；已经提交 MySQL 的 index_pending 不回退到草稿。
    await db.execute(update(ProductUpdate).where(ProductUpdate.status == 'processing')
        .values(status='extract_failed', version=ProductUpdate.version + 1,
                error_code='PROCESS_RESTARTED', error_message='上次提取因服务重启中断，请重新生成草稿', updated_at=now()))
