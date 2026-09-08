import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client.js'
import { useToast } from '../../store/useToast.jsx'
import ModeTabs from './ModeTabs.jsx'
import ReferenceDropzone from './ReferenceDropzone.jsx'
import PresetSelector from './PresetSelector.jsx'
import PresetStatusBanner from './PresetStatusBanner.jsx'
import AdvancedPanel from './AdvancedPanel.jsx'
import PreviewPanel from './PreviewPanel.jsx'
import HistoryPanel from './HistoryPanel.jsx'
import LoraPicker from './LoraPicker.jsx'

const REF_CATEGORY = { image: 'images', video: 'videos', audio: 'audio' }

function categoryFor(file) {
  if (file.type?.startsWith('video')) return REF_CATEGORY.video
  if (file.type?.startsWith('audio')) return REF_CATEGORY.audio
  return REF_CATEGORY.image
}

export default function GenerationWorkspace({ kind, title }) {
  const toast = useToast()
  const navigate = useNavigate()
  const [config, setConfig] = useState(null)

  const [presets, setPresets] = useState([])
  const [presetId, setPresetId] = useState(null)
  const [preset, setPreset] = useState(null) // resolvido (GET /api/presets/{id})

  const [mode, setMode] = useState(null)
  const [activeAddons, setActiveAddons] = useState([])
  const [controlVideoOpts, setControlVideoOpts] = useState([])
  const [selectedControlOpt, setSelectedControlOpt] = useState(null)

  const [loras, setLoras] = useState([])
  const [selectedLoras, setSelectedLoras] = useState({})

  const [formats, setFormats] = useState({})
  const [format, setFormat] = useState('16:9')
  const [resolution, setResolution] = useState('')
  const [qualityPresets, setQualityPresets] = useState({})
  const [quality, setQuality] = useState('BALANCED')
  const [steps, setSteps] = useState('Auto')
  const [advancedFields, setAdvancedFields] = useState([])
  const [advancedValues, setAdvancedValues] = useState({})

  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [sourceStrength, setSourceStrength] = useState(0.6)
  const [duration, setDuration] = useState(5)
  const [seed, setSeed] = useState(-1)
  const [refs, setRefs] = useState({})
  const [extraValues, setExtraValues] = useState({})

  const [job, setJob] = useState(null)
  const [recentJobs, setRecentJobs] = useState([])
  const pollRef = useRef(null)

  // --- carregar configuração do studio + lista de presets (dropdown dinâmico) ---
  useEffect(() => {
    let mounted = true
    Promise.all([
      api.config.studio(kind),
      api.presets.list(kind),
      api.loras.list(),
      api.config.formats(),
      api.config.qualityPresets(),
      api.config.advancedFields(),
      api.config.controlVideo(),
    ]).then(([cfg, presetList, loraList, fmts, qp, adv, cv]) => {
      if (!mounted) return
      setConfig(cfg)
      setPresets(presetList)
      setPresetId(presetList[0]?.id || null)
      setLoras(loraList)
      setFormats(fmts)
      setQualityPresets(qp)
      setAdvancedFields(adv)
      setControlVideoOpts(cv)
    }).catch(() => toast.error(`Não foi possível carregar a configuração de ${title}.`))

    refreshHistory()
    return () => { mounted = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  // --- ao trocar de preset, resolver por completo e aplicar defaults/capabilities ---
  useEffect(() => {
    if (!presetId) return
    let mounted = true
    api.presets.get(presetId).then((resolved) => {
      if (!mounted) return
      setPreset(resolved)
      setMode(resolved.modes?.[0])
      const d = resolved.defaults || {}
      if (d.quality) setQuality(d.quality)
      if (d.steps !== undefined) setSteps(d.steps)
      if (d.duration_seconds !== undefined) setDuration(d.duration_seconds)
      if (d.format) setFormat(d.format)
      setSelectedLoras({})
      setActiveAddons([])
      setSelectedControlOpt(null)
    }).catch(() => toast.error('Não foi possível carregar este preset.'))
    return () => { mounted = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetId])

  useEffect(() => {
    if (formats[format]) setResolution(formats[format].resolutions[1] || formats[format].resolutions[0])
  }, [format, formats])

  const refreshHistory = () => {
    api.jobs.list().then((all) => setRecentJobs(all.filter((j) => j.kind === kind))).catch(() => {})
  }

  // --- derivar, a partir das capabilities (array) do preset, o que a UI mostra ---
  const caps = new Set(preset?.capabilities || [])
  const visibleModes = (config?.modes || []).filter((m) => !preset || preset.modes?.includes(m.id))
  const currentModeDef = visibleModes.find((m) => m.id === mode)

  const neededZoneKeys = new Set()
  visibleModes.forEach((m) => (m.needs || []).forEach((k) => neededZoneKeys.add(k)))
  if (caps.has('audio_to_video')) neededZoneKeys.add('audio')
  if (caps.has('control_video')) neededZoneKeys.add('control_video')
  // "reference_images" em modelos de áudio significa "aceita um áudio de referência"
  // (config_importer.py reaproveita este nome vindo do campo audio_prompt_type real
  // do Wan2GP) — só faz sentido no módulo de áudio, nunca nos outros.
  if (kind === 'audio' && caps.has('reference_images')) neededZoneKeys.add('reference_audio')
  const visibleZones = (config?.reference_zones || []).filter((z) => neededZoneKeys.has(z.key))

  const visibleAddons = (config?.addons || []).filter((a) => {
    if (a.id === 'control_video') return caps.has('control_video')
    if (a.id === 'frame_inject') return caps.has('injected_frames')
    if (a.id === 'end_frame') return caps.has('end_frame')
    return true
  })

  const hasLora = caps.has('lora')
  const needsSourceStrength = config?.has_source_strength &&
    (currentModeDef?.needs?.includes('start_image') || currentModeDef?.needs?.includes('reference_image'))

  const toggleAddon = (id) => {
    setActiveAddons((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]))
  }
  const setAdvanced = (id, val) => setAdvancedValues((prev) => ({ ...prev, [id]: val }))
  const setExtra = (id, val) => setExtraValues((prev) => ({ ...prev, [id]: val }))

  const toggleLora = (id) => {
    setSelectedLoras((prev) => {
      const next = { ...prev }
      if (id in next) delete next[id]
      else next[id] = loras.find((l) => l.id === id)?.strength ?? 1
      return next
    })
  }
  const setLoraStrength = (id, strength) => setSelectedLoras((prev) => ({ ...prev, [id]: strength }))

  const pollJob = useCallback((jobId) => {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const j = await api.jobs.get(jobId)
        setJob(j)
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status)) {
          clearInterval(pollRef.current)
          if (j.status === 'COMPLETED') toast.success('Geração concluída.')
          if (j.status === 'FAILED') toast.error(`Falhou: ${j.error || 'erro desconhecido'}`)
          refreshHistory()
        }
      } catch {
        clearInterval(pollRef.current)
        toast.error('Perdeu-se a ligação ao backend a meio da geração.')
      }
    }, 700)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const [uploading, setUploading] = useState(false)

  // Envia cada referência para /api/assets (fica gravada localmente no
  // Studio) e devolve {zoneKey: path} — é este path absoluto que o
  // CloudWorkerEngine reenvia ao Worker (POST /upload-ref|/upload-audio)
  // antes de submeter o job. Uma referência já vinda do servidor (ex.:
  // "Estender" a partir de uma geração anterior) tem isServerRef=true e
  // o seu path é reaproveitado sem novo upload.
  const uploadReferences = async () => {
    const uploaded = {}
    for (const [zoneKey, value] of Object.entries(refs)) {
      if (!value) continue
      if (value.isServerRef) {
        uploaded[zoneKey] = value.path
        continue
      }
      const result = await api.assets.upload(value, categoryFor(value))
      uploaded[zoneKey] = result.path
    }
    return uploaded
  }

  const generate = async () => {
    if (!presetId) {
      toast.error('Escolhe um preset antes de gerar.')
      return
    }
    setUploading(true)
    let uploadedRefs
    try {
      uploadedRefs = await uploadReferences()
    } catch (e) {
      setUploading(false)
      toast.error(`Falha ao enviar referência: ${e.message}`)
      return
    }
    setUploading(false)

    const parameters = {
      format: config?.has_format ? format : undefined,
      resolution: config?.has_format ? resolution : undefined,
      quality, steps,
      duration_seconds: config?.has_duration ? duration : undefined,
      seed, source_strength: needsSourceStrength ? sourceStrength : undefined,
      negative_prompt: negativePrompt,
      addons: activeAddons,
      control_video_option: selectedControlOpt,
      loras: Object.entries(selectedLoras).map(([id, strength]) => ({ id, strength })),
      ...uploadedRefs,
      advanced: advancedValues,
      extra: extraValues,
    }
    try {
      const created = await api.jobs.create({ preset_id: presetId, mode, kind, prompt, parameters })
      setJob({ id: created.id, status: 'QUEUED', progress: 0 })
      pollJob(created.id)
      toast.info('Job enviado para a fila.')
    } catch (e) {
      toast.error(`Não foi possível criar o job: ${e.message}`)
    }
  }

  const cancelJob = async () => {
    if (job?.id) {
      try {
        await api.jobs.cancel(job.id)
        clearInterval(pollRef.current)
        setJob((j) => ({ ...j, status: 'CANCELLED' }))
        toast.info('Job cancelado.')
      } catch (e) {
        toast.error(`Não foi possível cancelar: ${e.message}`)
      }
    }
  }

  if (!config) {
    return <div style={{ color: 'var(--text-1)' }}>A carregar {title}…</div>
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20 }}>
      <div style={{ minWidth: 0 }}>
        <h2 style={{ marginBottom: 16 }}>{title}</h2>

        <PresetStatusBanner preset={preset} />

        {visibleModes.length > 0 && <ModeTabs modes={visibleModes} activeMode={mode} onChange={setMode} />}

        {visibleAddons.length > 0 && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
            {visibleAddons.map((a) => (
              <button
                key={a.id}
                className={`chip ${activeAddons.includes(a.id) ? 'active' : ''}`}
                onClick={() => toggleAddon(a.id)}
              >
                + {a.label}
              </button>
            ))}
          </div>
        )}

        {activeAddons.includes('control_video') && (
          <div className="panel" style={{ padding: 14, marginBottom: 18 }}>
            <div className="label">Control Video — opção</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {controlVideoOpts.map((o) => (
                <button
                  key={o.id}
                  className={`chip ${selectedControlOpt === o.id ? 'active' : ''}`}
                  title={o.description}
                  onClick={() => setSelectedControlOpt(o.id)}
                >
                  {o.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {visibleZones.length > 0 && (
          <>
            <div className="label" style={{ marginTop: 4 }}>Referências</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10, marginBottom: 18 }}>
              {visibleZones.map((z) => (
                <ReferenceDropzone
                  key={z.key}
                  label={z.label}
                  accept={z.accept}
                  file={refs[z.key]}
                  onChange={(f) => setRefs((prev) => {
                    const next = { ...prev }
                    if (f) next[z.key] = f
                    else delete next[z.key]
                    return next
                  })}
                />
              ))}
            </div>
          </>
        )}

        <div className="panel" style={{ padding: 16, marginBottom: 18 }}>
          <label className="label">Prompt</label>
          <textarea
            className="input"
            rows={3}
            placeholder="Descreve o que queres gerar…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div style={{ fontSize: 11, color: 'var(--text-2)', textAlign: 'right', marginTop: 4, marginBottom: 10 }}>
            {prompt.length} caracteres
          </div>

          <label className="label">Negative Prompt</label>
          <textarea
            className="input"
            rows={2}
            placeholder="O que evitar…"
            value={negativePrompt}
            onChange={(e) => setNegativePrompt(e.target.value)}
          />
        </div>

        {needsSourceStrength && (
          <div className="panel" style={{ padding: 16, marginBottom: 18 }}>
            <label className="label">Source Strength — {sourceStrength.toFixed(2)}</label>
            <input
              type="range" min="0" max="1" step="0.01"
              value={sourceStrength}
              onChange={(e) => setSourceStrength(parseFloat(e.target.value))}
              style={{ width: '100%' }}
            />
          </div>
        )}

        {config.extra_fields?.length > 0 && (
          <div style={{ marginBottom: 18 }}>
            <AdvancedPanel fields={config.extra_fields} values={extraValues} onChange={setExtra} />
          </div>
        )}

        {hasLora && (
          <div className="panel" style={{ padding: 16, marginBottom: 18 }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>LoRAs</div>
            {preset?.loras?.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                {preset.loras.map((l) => (
                  <span key={l.id} className="chip" title={l.url} style={{ opacity: l.installed ? 1 : 0.6 }}>
                    {l.required ? '★ ' : ''}{l.name}{l.installed ? '' : ' (não instalado)'}
                  </span>
                ))}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 10 }}>
              Recomendados por este preset acima · os teus LoRAs instalados abaixo
            </div>
            <LoraPicker loras={loras} selected={selectedLoras} onToggle={toggleLora} onStrengthChange={setLoraStrength} />
          </div>
        )}

        {advancedFields.length > 0 && (
          <div style={{ marginBottom: 18 }}>
            <AdvancedPanel fields={advancedFields} values={advancedValues} onChange={setAdvanced} />
          </div>
        )}
      </div>

      <div style={{ minWidth: 0 }}>
        {presets.length > 0 && <PresetSelector presets={presets} selectedId={presetId} onSelect={setPresetId} />}

        <div style={{ height: 14 }} />

        <div className="panel" style={{ padding: 16, marginBottom: 14 }}>
          <label className="label">Qualidade</label>
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            {Object.keys(qualityPresets).map((q) => (
              <button key={q} className={`chip ${quality === q ? 'active' : ''}`} onClick={() => setQuality(q)}>
                {qualityPresets[q].label}
              </button>
            ))}
          </div>

          <label className="label">Steps</label>
          <select className="input" value={steps} onChange={(e) => setSteps(e.target.value)} style={{ marginBottom: 12 }}>
            {['Auto', 8, 20, 30, 40, 50].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          {config.has_format && (
            <>
              <label className="label">Formato</label>
              <select className="input" value={format} onChange={(e) => setFormat(e.target.value)} style={{ marginBottom: 12 }}>
                {Object.keys(formats).map((f) => <option key={f} value={f}>{f}</option>)}
              </select>

              {formats[format] && (
                <>
                  <label className="label">Resolução</label>
                  <select className="input" value={resolution} onChange={(e) => setResolution(e.target.value)} style={{ marginBottom: 12 }}>
                    {formats[format].resolutions.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </>
              )}
            </>
          )}

          {config.has_duration && (
            <>
              <label className="label">Duração — {duration}s</label>
              <input
                type="range" min={config.duration_min} max={config.duration_max} step="1"
                value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                style={{ width: '100%', marginBottom: 12 }}
              />
            </>
          )}

          <label className="label">Seed</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              className="input" type="number" value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value || '0', 10))}
            />
            <button className="btn" onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}>🎲</button>
          </div>
        </div>

        <button
          className="btn btn-primary"
          style={{ width: '100%', justifyContent: 'center', padding: '11px 0', marginBottom: 14 }}
          onClick={generate}
          disabled={uploading}
        >
          {uploading ? 'A enviar referências…' : 'Gerar'}
        </button>

        <div style={{ marginBottom: 14 }}>
          <PreviewPanel
            job={job}
            onCancel={job && ['QUEUED', 'RUNNING', 'PROCESSING'].includes(job.status) ? cancelJob : null}
            onExtend={
              kind === 'video' && (config?.modes || []).some((m) => m.id === 'continue')
                ? () => {
                    setMode('continue')
                    setRefs((prev) => ({
                      ...prev,
                      reference_video: { name: (job.output_url || '').split('/').pop() || 'output', isServerRef: true, path: job.output_path },
                    }))
                    toast.info('Output carregado como vídeo de origem — modo Continue ativado.')
                  }
                : null
            }
          />
        </div>

        <HistoryPanel
          jobs={recentJobs}
          onSelect={(j) => { clearInterval(pollRef.current); setJob(j) }}
          onSeeAll={() => navigate('/library/gallery')}
        />
      </div>
    </div>
  )
}
