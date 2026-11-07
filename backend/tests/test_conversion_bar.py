from app import llm, runner
from app.modules import ALL_MODULES, get_module

SELLING = ('ugc_script', 'ad_script', 'ad_copy', 'voiceover', 'landing_copy', 'email_sms')


def test_every_selling_module_carries_the_bar_and_the_selling_reference():
    for key in SELLING:
        module = get_module(key)
        assert 'CONVERSION BAR' in module.instructions, key
        assert 'selling-elements.md' in module.refs, key
    # Reviews judge copy; they are not asked to write it.
    for module in ALL_MODULES:
        if module.kind == 'review':
            assert 'CONVERSION BAR' not in module.instructions, module.key


def test_ugc_is_built_to_sell():
    module = get_module('ugc_script')
    assert module.tier == 'deep'
    assert 'questioning-flows.md' not in module.refs  # intake is already answered
    fields = {f.name: f for f in module.fields}
    assert fields['avatar'].assist == 'extract' and fields['offer'].assist == 'extract'
    for beat in ('objection', 'Value math', 'reason to act now', 'mechanism shown on camera', 'ranking'):
        assert beat in module.instructions, beat


async def test_ugc_prompt_reaching_the_model_has_the_selling_machinery(env, monkeypatch):
    api = env['api']
    await api.post(f"/api/brands/{env['brand']}/products", json={'name': 'ERASE Spray', 'price': 349})
    await api.post(f"/api/brands/{env['brand']}/avatars", json={'name': 'نور، 27، عندها قطتين'})
    seen = []

    async def capture(request):
        seen.append(request)
        yield llm.Chunk('text', 'سكريبت')
        yield llm.Chunk('usage', usage=llm.Usage(model=request.model, input_tokens=1, output_tokens=1))
    monkeypatch.setattr(llm, 'stream', capture)

    response = await api.post('/api/runs', json={
        'brand_id': env['brand'], 'module_key': 'ugc_script',
        'inputs': {'product': 'ERASE Spray', 'avatar': 'نور، 27، عندها قطتين'}})
    assert response.status_code == 201, response.text
    await runner.execute(response.json()['id'])

    request = seen[0]
    assert request.model == 'claude-opus-5'
    assert 'REFERENCE FILE: references/selling-elements.md' in request.skill_text
    assert 'Objection Deconstruction Matrix' in request.skill_text
    assert 'CONVERSION BAR' in request.task and 'CONVERSION BAR' not in request.context_text
    assert 'نور، 27، عندها قطتين' in request.task
    assert 'ERASE Spray' in request.context_text and '349' in request.context_text
