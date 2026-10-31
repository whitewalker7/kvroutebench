let data, timer;
const names = {round_robin: 'Round-robin', cache_aware: 'Cache-aware'};
const $ = id => document.getElementById(id);
const ms = n => `${n.toFixed(1)} ms`;
function inspect(policy, row) {
  $('detail-title').textContent = `${names[policy]} · request ${row.index + 1} · family ${'ABC'[row.family]}`;
  $('detail-text').textContent = `Worker ${new URL(row.worker).port} reused ${row.cached_tokens} / ${row.prompt_tokens} prompt tokens and processed ${row.prompt_tokens - row.cached_tokens} afresh. Client TTFT: ${ms(row.ttft_ms)}. Server prompt processing: ${ms(row.prompt_ms)}. Total response: ${ms(row.end_to_end_ms)}.`;
  $('raw-link').hidden = false;
  $('raw-link').href = row.raw_url;
  document.querySelectorAll('.request').forEach(b => b.classList.toggle('selected', b.dataset.key === `${policy}-${row.index}`));
}
function render() {
  const step = Number($('step').value);
  $('step-label').textContent = `${step} / 12`;
  const max = Math.ceil(Math.max(...Object.values(data.policies).flatMap(p => p.rows.map(r => r.ttft_ms))) / 500) * 500;
  const panels = $('panels'); panels.replaceChildren();
  for (const [policy, info] of Object.entries(data.policies)) {
    const panel = document.createElement('article'); panel.className = 'panel';
    panel.innerHTML = `<div class="panel-top"><div><h3>${names[policy]}</h3><p>${policy === 'round_robin' ? 'Alternate worker assignments' : 'Prefer matching cached prefixes'}</p></div><span class="policy-pill">SMG 1.13.0</span></div><div class="lane-head"><span>#</span><span>SET</span><span>PORT</span><span>TTFT · 0–${max} ms</span><span>TIME</span></div>`;
    for (const row of info.rows) {
      const pending = row.index >= step;
      const button = document.createElement('button');
      button.className = `request${pending ? ' pending' : ''}`;
      button.dataset.key = `${policy}-${row.index}`;
      button.disabled = pending;
      button.setAttribute('aria-label', `${names[policy]}, request ${row.index+1}, family ${'ABC'[row.family]}, ${ms(row.ttft_ms)}`);
      const large = (row.prompt_tokens - row.cached_tokens) > row.prompt_tokens / 2;
      button.innerHTML = `<span class="index">${String(row.index+1).padStart(2,'0')}</span><span class="family ${'abc'[row.family]}">${'ABC'[row.family]}</span><span class="worker">${pending ? '—' : new URL(row.worker).port}</span><div class="bar-track"><div class="bar ${large ? '' : 'warm'}" style="width:${pending ? 0 : 100 * row.ttft_ms/max}%;visibility:${pending?'hidden':'visible'}"></div></div><span class="time">${pending ? '—' : row.ttft_ms.toFixed(1)+' ms'}</span>`;
      button.addEventListener('click', () => inspect(policy,row));
      panel.append(button);
    }
    const shown = info.rows.slice(0,step);
    const counts = ['8001','8002'].map(port => shown.filter(r => new URL(r.worker).port === port).length);
    const largeCount = shown.filter(r => r.prompt_tokens-r.cached_tokens > r.prompt_tokens/2).length;
    const foot = document.createElement('div'); foot.className='panel-foot';
    foot.innerHTML = `<span>Large prefills <b>${largeCount}</b></span><span>Worker requests <b>${counts[0]} / ${counts[1]}</b></span>`;
    panel.append(foot); panels.append(panel);
  }
}
function stop() { clearInterval(timer); timer=null; $('play').textContent='Replay saved run'; }
async function main() {
  const response = await fetch('data.json'); if(!response.ok) throw Error('Could not load recorded results.');
  data = await response.json();
  const rr=data.policies.round_robin.summary, ca=data.policies.cache_aware.summary;
  $('means').textContent=`${rr.mean_ttft_ms.toFixed(0)} → ${ca.mean_ttft_ms.toFixed(0)} ms`;
  $('saving').textContent=`${((1-ca.mean_ttft_ms/rr.mean_ttft_ms)*100).toFixed(1)}%`;
  $('reuse').textContent=`${(100*rr.token_weighted_reuse).toFixed(1)} → ${(100*ca.token_weighted_reuse).toFixed(1)}%`;
  const heavy = policy => data.policies[policy].rows.filter(r => r.prompt_tokens-r.cached_tokens > r.prompt_tokens/2).length;
  $('finding').textContent=`${heavy('round_robin')} large prefills became ${heavy('cache_aware')}.`;
  $('seed').textContent=data.manifest.seed;
  $('run-id').textContent=data.run_id;
  ['play','reset','step'].forEach(id => $(id).disabled=false);
  $('play').addEventListener('click',()=>{if(timer){stop();return;} if(Number($('step').value)>=12)$('step').value=0; render(); $('play').textContent='Pause replay'; timer=setInterval(()=>{$('step').value=Number($('step').value)+1;render();if(Number($('step').value)>=12)stop();},850);});
  $('reset').addEventListener('click',()=>{stop();$('step').value=0;render();});
  $('step').addEventListener('input',()=>{stop();render();});
  render();
}
main().catch(error=>{$('error').hidden=false;$('error').textContent=`${error.message} Start the demo with python3 scripts/serve-demo.py.`;});
