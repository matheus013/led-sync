# LED Sync

Controla e sincroniza todos os LEDs RGB do PC a partir de uma única interface, usando o servidor SDK do [OpenRGB](https://openrgb.org).

## Dispositivos testados
- Placa-mãe ASUS ROG STRIX B550-A (Aura + conector ARGB do gabinete)
- Memória HyperX Predator RGB
- Mouse Logitech G703 LIGHTSPEED

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
- Fechar a janela não para os LEDs; use **Encerrar** para parar o app.
- Em "Addressable RGB Header", informe quantos LEDs estão ligados no conector ARGB.
- `config.json` guarda efeito, cores, brilho e tamanhos das zonas.
