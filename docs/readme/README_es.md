<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/assets/brand/nanomuse-cover.png" alt="nanoMuse: un agente personal de código abierto para todos tus dispositivos">
</p>

<p align="center">
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/README.md">English</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_zh.md">简体中文</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_zh-TW.md">繁體中文</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_es.md">Español</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_fr.md">Français</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_id.md">Bahasa Indonesia</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ja.md">日本語</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ko.md">한국어</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ru.md">Русский</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_vi.md">Tiếng Việt</a>
</p>
<p align="center">
  <a href="https://github.com/nano-muse/nanoMuse/stargazers"><img src="https://img.shields.io/github/stars/nano-muse/nanoMuse?style=flat&label=stars" alt="Estrellas en GitHub"></a>
  <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/github/downloads/nano-muse/nanoMuse/total?label=downloads" alt="Descargas"></a>
  <a href="https://github.com/nano-muse/nanoMuse/actions/workflows/ci.yml"><img src="https://github.com/nano-muse/nanoMuse/actions/workflows/ci.yml/badge.svg?branch=main" alt="Test Suite"></a>
  <a href="https://demo.nanomuse.dev/"><img src="https://img.shields.io/badge/Pru%C3%A9balo-demo.nanomuse.dev-0a66e4" alt="Pruébalo en el navegador"></a>
  <a href="https://nanomuse.cn/"><img src="https://img.shields.io/badge/Sitio_web-nanomuse.cn-0a66e4" alt="Sitio web"></a>
  <a href="https://arxiv.org/abs/2610.08699"><img src="https://img.shields.io/badge/arXiv-2610.08699-b31b1b" alt="Artículo en arXiv"></a>
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nano-muse/nanoMuse?label=license" alt="GPL-3.0-or-later"></a>
  <a href="https://discord.gg/bkTySmm28X"><img src="https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

**nanoMuse es un agente personal de código abierto para todos tus dispositivos.** Un solo agente con nombre y aspecto propios, al estilo del [Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) de Meta: hace cosas en vez de responder preguntas, sigue trabajando con la app cerrada, se acuerda de ti y se detiene a preguntar antes de cualquier cosa que no podrías deshacer.

*nano* significa el conjunto completo, lo bastante pequeño para que lo ejecutes y lo despliegues tú mismo: la app del teléfono, la de escritorio, la consola web y el relay que las une están en este repositorio, bajo GPL-3.0-or-later. **[Gratuito, de código abierto y sin ánimo de lucro. Construyámoslo juntos.](../../CONTRIBUTING.md)** Al iniciar sesión recibes un crédito gratuito de uso de modelos en el relay de la comunidad (lo paga el desarrollador); cuando se agota, [usa tu propia clave](../own-key.md). El mismo relay funciona en un servidor tuyo, así que nada tiene que salir de casa. Última versión: **1.0.1 Ballast**, [notas de la versión](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.1) · [pruébalo en el navegador](https://demo.nanomuse.dev/).

https://github.com/user-attachments/assets/c7694d5a-9450-4f99-9254-5d70560d7565

<p align="center"><a href="https://nanomuse.cn/media/film/nanomuse-film-en-web.mp4">English</a> · <a href="https://nanomuse.cn/media/film/nanomuse-film-zh-web.mp4">中文</a> · <a href="https://nanomuse.cn/#film">nanomuse.cn</a></p>

## 🗞️ Novedades

- `2026-10-09` 🚀 Ya está la versión [1.0.0 Keel](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0), para el teléfono, el ordenador y el navegador; se instala sobre la anterior conservando tus datos, y sus notas de la versión recogen cada cambio.
- `2026-10-08` 🤗 Nuestro artículo está en [Hugging Face Daily Papers](https://huggingface.co/papers/2610.08699), tercero en la lista del 8 de octubre; las preguntas y los comentarios son bienvenidos en la página del artículo.
- `2026-10-07` 📄 Nuestro artículo está disponible en [arXiv](https://arxiv.org/abs/2610.08699): *nanoMuse: An Open-Source Personal Agent for Every Device You Own*, de Guangyi Liu, Yong Liu y Jiangning Zhang (Universidad de Zhejiang); la cita está al final de esta página.
- `2026-09-25` 🎉 nanoMuse se publica en GitHub bajo GPL-3.0-or-later: una aplicación Android construida sobre OpenMinis 1.13; el relay, la aplicación de escritorio y la aplicación para iPhone llegaron en los días siguientes.

Todas las versiones: [releases](https://github.com/nano-muse/nanoMuse/releases).

## Instalación

| | |
|---|---|
| **Navegador** | [demo.nanomuse.dev](https://demo.nanomuse.dev/): un nanoMuse en un teléfono simulado, tras iniciar sesión. Es una demo; las apps de abajo son las de verdad |
| **Android** 8.0+, arm64 | [nanoMuse-1.0.1-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-1.0.1-arm64.apk): todas las versiones se firman con la misma clave y se instalan sobre la anterior |
| **iPhone / iPad** | [TestFlight](https://testflight.apple.com/join/ZHexbDqc): una beta que pasó la revisión beta de Apple; el enlace la instala · [iOS](../ios.md) |
| **macOS** 12+ | [Apple Silicon](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-mac-arm64.dmg) · [Intel](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-mac-x64.dmg): sin notarizar: la primera vez, clic derecho → *Abrir* |
| **Windows** 10+ | [nanoMuse-Desktop-1.0.1-win-x64.exe](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-win-x64.exe): pulsa *Ejecutar de todos modos* una vez |
| **Linux** x64 | [AppImage](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-linux-x64.AppImage) · [.deb](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-linux-x64.deb) · [tar.gz](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.1/nanoMuse-Desktop-1.0.1-linux-x64.tar.gz) |
| **Docker** | `bash scripts/self-host.sh --local` para tu propio relay; `docker compose up -d app` para la app web en un servidor tuyo; véase [autoalojamiento](../self-hosting.md) |

Todas las descargas vienen de la [última versión](https://github.com/nano-muse/nanoMuse/releases/latest); los mismos archivos están en [nanomuse.cn/dl](https://nanomuse.cn/dl/) si GitHub va lento donde estás. Abre la app, inicia sesión con un correo o un número de teléfono de China continental, y el agente ya tiene un modelo con el que pensar. El teléfono, el escritorio y la web comparten una cuenta y muestran las mismas conversaciones.

## Qué hace

<table>
  <tr>
    <td width="50%" valign="top"><b>Hace cosas.</b><br>Una shell de Linux, un navegador, servidores MCP y habilidades, y, con <i>Manos</i> activado, las apps de tu teléfono y las ventanas de tu ordenador a través de su pantalla, para todo lo que nunca tuvo API.</td>
    <td width="50%" valign="top"><b>Pregunta primero.</b><br>Se detiene antes de borrar, enviar o pagar, y recuerda tu respuesta para una vez, para este chat o para siempre; las contraseñas y los códigos los escribes tú. Si hay que iniciar sesión o resolver un CAPTCHA, te lo deja a ti; <i>Listo</i> reanuda.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>Llega a tus otros dispositivos.</b><br>Dilo en el teléfono y se ejecuta en tu PC; <code>@Mac …</code> al principio de un mensaje envía la tarea allí. Las aprobaciones vuelven al dispositivo que tienes en la mano.</td>
    <td width="50%" valign="top"><b>Sigue adelante.</b><br>Metas revisadas según un horario, rutinas que corren con la app cerrada, un feed escrito para ti cada mañana.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>Se acuerda de ti.</b><br>Qué es, qué sabe de ti y cuándo despierta son archivos Markdown que puedes leer y editar.</td>
    <td width="50%" valign="top"><b>Vive en tus apps de chat.</b><br>Responde en 飞书, 钉钉, 企业微信 y Telegram.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>Un aspecto propio.</b><br>Descríbelo, tu modelo de imagen lo dibuja, un modelo de vídeo lo hace moverse. Un dragoncito por defecto.</td>
    <td width="50%" valign="top"><b>Cualquier modelo.</b><br>El crédito del relay, tu propia clave en uno de diecinueve proveedores (Bailian, OpenRouter, OpenAI, Gemini, DeepSeek y más), o un plan que ya pagas: ChatGPT, Claude, Kimi. Si un proveedor no tiene modelos de imagen o vídeo, esas dos funciones quedan apagadas y la app lo dice.</td>
  </tr>
</table>

## Cómo funciona

Cada dispositivo ejecuta su propio agente: el teléfono dentro del APK (Alpine Linux bajo proot, una shell, un navegador, MCP), el ordenador dentro de nanoMuse Desktop (DeepSeek Harness con el runtime Python para las manos). Con la sesión iniciada se encuentran en el relay y pueden pedirse cosas; el texto de las conversaciones viaja por él, los archivos y las capturas se quedan donde se hicieron.

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/assets/brand/devices-loop.png" alt="Android, el escritorio (Mac, Windows, Linux), iPhone y iPad y la aplicación web alrededor de una misma cuenta: el relay da de alta a los dispositivos en la cuenta y lleva la conversación entre ellos" width="92%">
</p>

[docs/every-device.md](../every-device.md) explica los dispositivos, [docs/hub.md](../hub.md) los frames, [docs/cloud.md](../cloud.md) el relay, [docs/privacy.md](../privacy.md) qué guarda.

## Comparado con Muse y OpenMinis

| | Meta Muse | OpenMinis | nanoMuse |
|---|---|---|---|
| Dónde corre el agente | Una VM en la nube por usuario | El teléfono en el que está instalado | Tu teléfono, tu ordenador o un servidor tuyo, una cuenta para todos |
| Apps sin API | Fuera de alcance; la VM nunca toca tus dispositivos | Una CLI de accesibilidad en Android | La pantalla como mano en el teléfono y el ordenador: capturas, las API primero, tú tomas el control en los inicios de sesión. No en iOS, donde el sistema no lo permite |
| Otros dispositivos | Clientes de una VM | Solo el que lo tiene instalado | Los dispositivos se piden cosas por el hub, con las aprobaciones donde estés |
| Modelos | Los de Meta | Trae el tuyo | El crédito gratuito del relay, o los tuyos |
| Licencia | Cerrada | GPL-3.0 | GPL-3.0-or-later, construido sobre OpenMinis |

## Documentación

[nanomuse.cn/docs](https://nanomuse.cn/docs/): instalación por plataforma, todos los dispositivos, las manos, conectores, memoria, autoalojamiento, los protocolos. Las fuentes están en [docs/](../); qué cambió en cada versión, en el [CHANGELOG](../../CHANGELOG.md) y en [docs/releases/](../releases/).

## Autoalojamiento

Un VPS, una hora: [docs/self-hosting.md](../self-hosting.md). Tres caminos: sin servidor, con tu propia clave; tu propio relay con `scripts/self-host.sh`; o un runtime propio para la app web.

## Contribuir

Úsalo para una tarea real, cuenta qué se rompió y luego elige algo concreto: [CONTRIBUTING.md](../../CONTRIBUTING.md) tiene la configuración y las convenciones, [AGENTS.md](../../AGENTS.md) las reglas que sigue un agente de programación en este repositorio, y la [hoja de ruta](../roadmap.md) dice por dónde empezar. [Issues](https://github.com/nano-muse/nanoMuse/issues) · [Discussions](https://github.com/nano-muse/nanoMuse/discussions) · [Discord](https://discord.gg/bkTySmm28X).

## ⭐️ Cita

Si nanoMuse te resulta útil, te agradecemos que cites el artículo.

```bibtex
@misc{liu2026nanomuseopensourcepersonalagent,
      title={nanoMuse: An Open-Source Personal Agent for Every Device You Own}, 
      author={Guangyi Liu and Yong Liu and Jiangning Zhang},
      year={2026},
      eprint={2610.08699},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2610.08699}, 
}
```

## Agradecimientos

nanoMuse se apoya en el trabajo de otros; [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) recoge las licencias.

- [OpenMinis](https://github.com/OpenMinis/OpenMinis): el agente en el dispositivo sobre el que está construida la app del teléfono, con [proot](https://github.com/nano-muse/proot) y [Alpine Linux](https://alpinelinux.org/) para el sandbox.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): el harness de agentes del que la app de escritorio es un plugin.
- [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) (ByteDance): el operador de las manos del escritorio es una adaptación del suyo, y los marcadores del escenario siguen su ScreenMarker.
- [MobileGym](https://github.com/Purewhiter/mobilegym), [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench), [PhoneHarness](https://github.com/PhoneHarness/PhoneHarness), [CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse), [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM), [ClawGUI](https://github.com/ZJU-REAL/ClawGUI): el operador del teléfono, las trazas y las ideas de producto.

## Aviso

nanoMuse es un proyecto comunitario independiente, no afiliado a Meta Platforms, Inc. ni respaldado por ella; Muse es su marca registrada. El dragón es del proyecto.

## Licencia

[GPL-3.0-or-later](../../LICENSE). La app del teléfono se basa en OpenMinis 1.13 (GPL-3.0), modificada desde el 2026-09-24; véase [NOTICE](../../NOTICE). Las versiones anteriores de la línea Python eran MIT (etiqueta `pre-openminis`).
