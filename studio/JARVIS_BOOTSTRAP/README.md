# JARVIS_BOOTSTRAP

Arquitetura (não implementação) para provisionar automaticamente uma GPU
cloud descartável no futuro: instalar dependências, o Worker, o engine,
modelos e LoRAs — tudo a partir de um manifest.

**Nada aqui descarrega modelos nem cria GPU.** Isto só mostra o plano.

## Uso

```
python cli.py --engine ltx
python cli.py --engine wan
```

## Adicionar um engine novo

Criar `manifests/<nome>.json` seguindo a forma de `ltx.example.json`.
Não é preciso mudar código.

## Como isto se liga ao resto do JARVIS

```
JARVIS STUDIO -> JARVIS API -> CLOUD WORKER -> GPU -> OUTPUT
```

Quando o Cloud Worker avançar para lá da arquitetura, um
`CloudProvider` (`backend/app/engines/cloud/providers.py`) vai chamar
`deploy(instance_id, manifest)` com o manifest lido aqui.
