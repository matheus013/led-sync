# LED Sync

Controla e sincroniza todos os LEDs RGB do PC a partir de uma única interface, usando o servidor SDK do [OpenRGB](https://openrgb.org).

## Dispositivos testados
- Placa-mãe ASUS ROG STRIX B550-A (Aura + conector ARGB do gabinete)
- Memória HyperX Predator RGB
- Mouse Logitech G703 LIGHTSPEED
- Placa de vídeo GALAX RTX 4070 Ti EX Gamer White V2 (controle direto via I2C da GPU, `galax_gpu.py`)

## Placa de vídeo Galax
O OpenRGB não reconhece a 4070 Ti EX Gamer White V2. O `galax_gpu.py` usa o mesmo protocolo
"Galax v2" do OpenRGB (registradores de cor `0x02-0x04`, modo `0x30`, sync `0x27`, salvar `0x40`)
via NvAPI I2C no endereço `0x50`; esta placa responde com a assinatura `02 01`.
Diagnóstico somente leitura: `python galax_gpu.py probe`.

## Efeitos
| Efeito | Descrição |
|---|---|
| Estático / Respiração / Espectro | todos os dispositivos na mesma cor |
| Arco-íris / Gradiente | onda de cor percorrendo os dispositivos |
| ♪ Pulso | cor 1 no volume, cor 2 nas batidas do grave |
| ♪ Batida | muda de cor a cada batida |
| ♪ Equalizador | espectro grave → agudo em cada peça |
| Nativo | grava a cor no hardware (funciona com o app fechado) |

Os modos ♪ capturam o áudio que sai pela saída padrão do Windows (loopback WASAPI).

## Instalação
```powershell
powershell -ExecutionPolicy Bypass -File instalar.ps1
```
Instala o OpenRGB e as dependências Python, e cria os atalhos na Área de Trabalho e na pasta Inicializar (roda em segundo plano com o Windows).

## Uso
- Abra pelo atalho **LED Sync**: a interface fica em `http://127.0.0.1:7777`.
- Ícone na bandeja (perto do relógio): clique para abrir o painel; botão direito para efeito, cor, brilho, dispositivos, ligar/desligar e encerrar.
- Fechar a janela não para os LEDs; use **Encerrar** para parar o app.
- Em "Addressable RGB Header", informe quantos LEDs estão ligados no conector ARGB.
- `config.json` guarda efeito, cores, brilho e tamanhos das zonas.
