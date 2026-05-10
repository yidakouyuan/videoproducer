[presentation.html](https://github.com/user-attachments/files/27563977/presentation.html)# VideoClaw

基于 [OpenClaw](https://openclaw.ai) 的多 Agent 短视频自动化生产系统。
[Upload<!DOCTYPE html>
<html lang="zh-CN">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoClaw 产品设计与 Agent 架构展示</title>
    <style>
        :root {
            color-scheme: light;
            --bg: #f6f8fb;
            --surface: #ffffff;
            --surface-soft: #eef4f7;
            --ink: #17202a;
            --ink-2: #344054;
            --muted: #667085;
            --line: #d9e2ec;
            --line-strong: #bdc9d6;
            --blue: #2563eb;
            --blue-soft: #dbeafe;
            --teal: #0f766e;
            --teal-soft: #ccfbf1;
            --orange: #ea580c;
            --orange-soft: #ffedd5;
            --rose: #e11d48;
            --rose-soft: #ffe4e6;
            --violet: #6d28d9;
            --violet-soft: #ede9fe;
            --green: #15803d;
            --green-soft: #dcfce7;
            --shadow: 0 22px 50px rgba(23, 32, 42, 0.10);
            --radius: 8px;
            --max: 1180px;
        }

        * {
            box-sizing: border-box;
        }

        html {
            scroll-behavior: smooth;
        }

        body {
            margin: 0;
            background: var(--bg);
            color: var(--ink);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 16px;
            line-height: 1.6;
            letter-spacing: 0;
            overflow-x: hidden;
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        button,
        input,
        textarea {
            font: inherit;
        }

        .topbar {
            position: sticky;
            top: 0;
            z-index: 50;
            border-bottom: 1px solid rgba(217, 226, 236, 0.85);
            background: rgba(246, 248, 251, 0.88);
            backdrop-filter: blur(14px);
        }

        .nav {
            max-width: var(--max);
            margin: 0 auto;
            min-height: 64px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 24px;
            padding: 0 24px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 164px;
            font-weight: 800;
            color: var(--ink);
        }

        .brand-mark {
            width: 30px;
            height: 30px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: var(--ink);
            color: #fff;
            font-size: 13px;
            letter-spacing: 0;
        }

        .nav-links {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--muted);
            font-size: 14px;
        }

        .nav-links a {
            padding: 8px 10px;
            border-radius: 999px;
        }

        .nav-links a.active,
        .nav-links a:hover {
            background: var(--surface);
            color: var(--blue);
            box-shadow: 0 0 0 1px var(--line);
        }

        .progress-rail {
            position: absolute;
            left: 0;
            bottom: -1px;
            width: 100%;
            height: 2px;
            background: transparent;
        }

        .progress-bar {
            height: 2px;
            width: 0;
            background: linear-gradient(90deg, var(--blue), var(--teal), var(--orange));
        }

        main {
            overflow: hidden;
        }

        .section {
            padding: 88px 24px;
        }

        .section.alt {
            background: var(--surface);
        }

        .wrap {
            max-width: var(--max);
            margin: 0 auto;
        }

        .hero {
            position: relative;
            min-height: calc(100vh - 220px);
            display: grid;
            align-items: center;
            padding: 34px 24px 32px;
            border-bottom: 1px solid var(--line);
            background:
                linear-gradient(90deg, rgba(37, 99, 235, 0.08), transparent 34%),
                linear-gradient(180deg, #ffffff 0%, #f6f8fb 100%);
        }

        .hero::after {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            height: 64px;
            background-image:
                linear-gradient(var(--line) 1px, transparent 1px),
                linear-gradient(90deg, var(--line) 1px, transparent 1px);
            background-size: 32px 32px;
            opacity: 0.28;
            pointer-events: none;
        }

        .hero-grid {
            position: relative;
            z-index: 1;
            max-width: var(--max);
            margin: 0 auto;
            display: grid;
            grid-template-columns: minmax(0, 0.88fr) minmax(400px, 1.12fr);
            gap: 36px;
            align-items: center;
        }

        .hero-grid > *,
        .section-head > *,
        .grid-3 > *,
        .grid-2 > *,
        .architecture > *,
        .decision-grid > *,
        .validation > *,
        .result-grid > *,
        .talk-track > * {
            min-width: 0;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-height: 32px;
            padding: 5px 10px;
            border-radius: 999px;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.78);
            color: var(--muted);
            font-size: 13px;
            font-weight: 700;
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--teal);
            box-shadow: 0 0 0 5px rgba(15, 118, 110, 0.10);
        }

        .nowrap {
            white-space: nowrap;
        }

        .mobile-only {
            display: none;
        }

        h1,
        h2,
        h3,
        p {
            margin: 0;
        }

        h1 {
            margin-top: 22px;
            font-size: clamp(38px, 4.9vw, 62px);
            line-height: 1.02;
            letter-spacing: 0;
            max-width: 780px;
            overflow-wrap: anywhere;
        }

        .hero-copy {
            margin-top: 24px;
            max-width: 650px;
            width: 100%;
            color: var(--ink-2);
            font-size: clamp(18px, 2.2vw, 23px);
            line-height: 1.55;
        }

        .hero-actions {
            margin-top: 34px;
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            min-height: 44px;
            padding: 0 16px;
            border: 1px solid var(--line-strong);
            border-radius: 8px;
            background: var(--surface);
            color: var(--ink);
            font-weight: 800;
            cursor: pointer;
        }

        .btn.primary {
            border-color: var(--ink);
            background: var(--ink);
            color: #fff;
        }

        .btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(23, 32, 42, 0.10);
        }

        .hero-stats {
            margin-top: 36px;
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            max-width: 650px;
        }

        .stat {
            border-top: 2px solid var(--line);
            padding-top: 12px;
        }

        .stat strong {
            display: block;
            color: var(--ink);
            font-size: 28px;
            line-height: 1;
        }

        .stat span {
            display: block;
            margin-top: 8px;
            color: var(--muted);
            font-size: 13px;
        }

        .product-visual {
            position: relative;
            min-height: 560px;
        }

        .flow-canvas {
            position: absolute;
            inset: -28px;
            width: calc(100% + 56px);
            height: calc(100% + 56px);
            pointer-events: none;
        }

        .mock-system {
            position: relative;
            min-height: 548px;
            display: grid;
            grid-template-columns: 0.78fr 1fr;
            gap: 14px;
            align-items: stretch;
        }

        .phone {
            align-self: center;
            border: 1px solid #1f2937;
            background: #111827;
            color: #fff;
            border-radius: 28px;
            padding: 12px;
            box-shadow: var(--shadow);
            min-height: 430px;
        }

        .phone-screen {
            min-height: 406px;
            border-radius: 20px;
            background: #f9fafb;
            color: var(--ink);
            padding: 18px 14px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .phone-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }

        .chat {
            width: 92%;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 13px;
            line-height: 1.45;
        }

        .chat.user {
            margin-left: auto;
            background: var(--blue);
            color: #fff;
        }

        .chat.bot {
            background: #fff;
            border: 1px solid var(--line);
            color: var(--ink-2);
        }

        .status-list {
            margin-top: auto;
            display: grid;
            gap: 8px;
        }

        .status-line {
            display: grid;
            grid-template-columns: 18px 1fr auto;
            gap: 8px;
            align-items: center;
            font-size: 12px;
            color: var(--muted);
        }

        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--green);
        }

        .dashboard {
            position: relative;
            display: grid;
            grid-template-rows: auto 1fr auto;
            gap: 14px;
            align-self: center;
        }

        .dash-panel,
        .dash-stage,
        .output-panel {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.92);
            box-shadow: 0 14px 30px rgba(23, 32, 42, 0.08);
        }

        .dash-panel {
            padding: 16px;
        }

        .dash-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            font-size: 13px;
            color: var(--muted);
        }

        .dash-title strong {
            color: var(--ink);
            font-size: 16px;
        }

        .run-id {
            padding: 3px 8px;
            border: 1px solid var(--line);
            border-radius: 999px;
            background: var(--surface-soft);
            font-size: 12px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }

        .agent-grid {
            margin-top: 16px;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }

        .agent-chip {
            min-height: 58px;
            display: grid;
            grid-template-columns: 34px 1fr;
            gap: 10px;
            align-items: center;
            padding: 9px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #fff;
        }

        .agent-icon {
            width: 34px;
            height: 34px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            color: var(--ink);
            font-size: 13px;
            font-weight: 900;
        }

        .agent-chip b {
            display: block;
            font-size: 13px;
            line-height: 1.1;
        }

        .agent-chip span {
            display: block;
            margin-top: 5px;
            color: var(--muted);
            font-size: 11px;
            line-height: 1.2;
        }

        .bg-blue {
            background: var(--blue-soft);
            color: var(--blue);
        }

        .bg-teal {
            background: var(--teal-soft);
            color: var(--teal);
        }

        .bg-orange {
            background: var(--orange-soft);
            color: var(--orange);
        }

        .bg-violet {
            background: var(--violet-soft);
            color: var(--violet);
        }

        .bg-rose {
            background: var(--rose-soft);
            color: var(--rose);
        }

        .bg-green {
            background: var(--green-soft);
            color: var(--green);
        }

        .dash-stage {
            padding: 16px;
        }

        .stage-track {
            display: grid;
            gap: 11px;
        }

        .stage-row {
            display: grid;
            grid-template-columns: 90px 1fr 64px;
            gap: 12px;
            align-items: center;
            color: var(--muted);
            font-size: 12px;
        }

        .bar {
            height: 8px;
            border-radius: 999px;
            background: var(--surface-soft);
            overflow: hidden;
        }

        .bar i {
            display: block;
            height: 100%;
            border-radius: inherit;
            background: var(--teal);
        }

        .output-panel {
            padding: 16px;
            display: grid;
            grid-template-columns: 92px 1fr;
            gap: 14px;
            align-items: center;
        }

        .video-tile {
            aspect-ratio: 9 / 16;
            border-radius: 8px;
            background:
                linear-gradient(180deg, rgba(23, 32, 42, 0.10), rgba(23, 32, 42, 0.70)),
                repeating-linear-gradient(135deg, #f97316 0 18px, #14b8a6 18px 36px, #2563eb 36px 54px);
            position: relative;
            overflow: hidden;
        }

        .video-tile::after {
            content: "▶";
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            width: 38px;
            height: 38px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.88);
            color: var(--ink);
            font-size: 15px;
            padding-left: 2px;
        }

        .metric-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }

        .metric-pills span {
            padding: 4px 8px;
            border-radius: 999px;
            background: var(--surface-soft);
            color: var(--muted);
            font-size: 12px;
            font-weight: 700;
        }

        .section-head {
            display: grid;
            grid-template-columns: minmax(0, 0.78fr) minmax(280px, 0.42fr);
            gap: 40px;
            align-items: end;
            margin-bottom: 36px;
        }

        .kicker {
            color: var(--blue);
            font-size: 13px;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        h2 {
            margin-top: 10px;
            font-size: clamp(32px, 5vw, 52px);
            line-height: 1.06;
            letter-spacing: 0;
        }

        .lead {
            color: var(--muted);
            font-size: 18px;
            line-height: 1.7;
        }

        .thesis {
            border-left: 4px solid var(--orange);
            padding: 12px 0 12px 18px;
            color: var(--ink-2);
            font-weight: 800;
            background: linear-gradient(90deg, rgba(255, 237, 213, 0.95), transparent);
        }

        .grid-3 {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 18px;
        }

        .grid-2 {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 18px;
        }

        .card {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
            padding: 22px;
            min-width: 0;
            box-shadow: 0 12px 28px rgba(23, 32, 42, 0.06);
        }

        .card.plain {
            box-shadow: none;
        }

        .card h3 {
            font-size: 20px;
            line-height: 1.25;
            margin: 0;
        }

        .card p {
            margin-top: 10px;
            color: var(--muted);
        }

        .label {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 34px;
            height: 30px;
            padding: 0 9px;
            margin-bottom: 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 900;
        }

        .persona {
            display: grid;
            gap: 14px;
        }

        .persona-row {
            display: grid;
            grid-template-columns: 112px 1fr;
            gap: 14px;
            padding: 14px 0;
            border-bottom: 1px solid var(--line);
        }

        .persona-row:last-child {
            border-bottom: 0;
        }

        .persona-row strong {
            color: var(--ink);
        }

        .persona-row span {
            color: var(--muted);
        }

        .priority-stack {
            display: grid;
            gap: 10px;
        }

        .priority {
            display: grid;
            grid-template-columns: 38px 1fr;
            gap: 12px;
            align-items: start;
            padding: 14px;
            border-radius: 8px;
            background: var(--surface-soft);
        }

        .priority b {
            display: block;
            line-height: 1.2;
        }

        .priority span {
            display: block;
            margin-top: 4px;
            color: var(--muted);
            font-size: 13px;
        }

        .num {
            width: 32px;
            height: 32px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: var(--ink);
            color: #fff;
            font-weight: 900;
            font-size: 13px;
        }

        .map-table {
            width: 100%;
            border-collapse: collapse;
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
        }

        .map-table th,
        .map-table td {
            padding: 16px;
            text-align: left;
            vertical-align: top;
            border-bottom: 1px solid var(--line);
        }

        .map-table th {
            color: var(--muted);
            background: #f8fafc;
            font-size: 13px;
            font-weight: 900;
        }

        .map-table tr:last-child td {
            border-bottom: 0;
        }

        .map-table td {
            color: var(--ink-2);
        }

        .map-table b {
            color: var(--ink);
        }

        .tag {
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            margin: 3px 4px 3px 0;
            padding: 2px 8px;
            border-radius: 999px;
            border: 1px solid var(--line);
            color: var(--muted);
            background: #fff;
            font-size: 12px;
            font-weight: 800;
            white-space: nowrap;
        }

        .architecture {
            display: grid;
            grid-template-columns: 0.9fr 1.1fr;
            gap: 22px;
            align-items: stretch;
        }

        .arch-map {
            position: relative;
            min-height: 640px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background:
                linear-gradient(90deg, rgba(37, 99, 235, 0.04), transparent),
                var(--surface);
            padding: 22px;
            overflow: hidden;
        }

        .arch-map::before {
            content: "";
            position: absolute;
            inset: 18px;
            border: 1px dashed var(--line-strong);
            border-radius: 8px;
            pointer-events: none;
        }

        .node {
            position: absolute;
            width: 172px;
            min-height: 72px;
            padding: 12px;
            border: 1px solid var(--line-strong);
            border-radius: 8px;
            background: #fff;
            box-shadow: 0 10px 22px rgba(23, 32, 42, 0.08);
        }

        .node small {
            display: block;
            color: var(--muted);
            font-size: 11px;
        }

        .node b {
            display: block;
            margin-top: 4px;
            font-size: 14px;
        }

        .node.user {
            left: 42px;
            top: 42px;
        }

        .node.orch {
            left: calc(50% - 86px);
            top: 56px;
            border-color: rgba(37, 99, 235, 0.55);
        }

        .node.tag {
            left: 60px;
            top: 186px;
        }

        .node.research {
            left: calc(50% - 86px);
            top: 184px;
            border-color: rgba(15, 118, 110, 0.50);
        }

        .node.writer {
            right: 60px;
            top: 186px;
        }

        .node.douyin {
            left: 78px;
            top: 332px;
        }

        .node.web {
            left: calc(50% - 86px);
            top: 342px;
        }

        .node.video {
            right: 60px;
            top: 332px;
            border-color: rgba(234, 88, 12, 0.55);
        }

        .node.publish {
            left: calc(50% - 86px);
            top: 500px;
        }

        .node.stats {
            right: 60px;
            top: 500px;
            border-color: rgba(21, 128, 61, 0.55);
        }

        .connector {
            position: absolute;
            height: 2px;
            background: var(--line-strong);
            transform-origin: left center;
        }

        .connector::after {
            content: "";
            position: absolute;
            right: -1px;
            top: -4px;
            width: 0;
            height: 0;
            border-left: 8px solid var(--line-strong);
            border-top: 5px solid transparent;
            border-bottom: 5px solid transparent;
        }

        .c1 {
            left: 214px;
            top: 78px;
            width: 154px;
        }

        .c2 {
            left: 368px;
            top: 130px;
            width: 116px;
            transform: rotate(90deg);
        }

        .c3 {
            left: 232px;
            top: 220px;
            width: 134px;
        }

        .c4 {
            left: 536px;
            top: 220px;
            width: 134px;
        }

        .c5 {
            left: 368px;
            top: 270px;
            width: 126px;
            transform: rotate(90deg);
        }

        .c6 {
            left: 232px;
            top: 368px;
            width: 132px;
        }

        .c7 {
            left: 536px;
            top: 376px;
            width: 134px;
        }

        .c8 {
            left: 536px;
            top: 535px;
            width: 134px;
        }

        .arch-notes {
            display: grid;
            gap: 18px;
        }

        .note {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
            padding: 20px;
        }

        .note h3 {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 19px;
        }

        .note ul,
        .talk-list {
            margin: 12px 0 0;
            padding-left: 20px;
            color: var(--muted);
        }

        .note li,
        .talk-list li {
            margin: 8px 0;
        }

        .decision-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 18px;
        }

        .decision {
            display: grid;
            grid-template-columns: 42px 1fr;
            gap: 14px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
            padding: 20px;
        }

        .decision h3 {
            font-size: 19px;
        }

        .decision dl {
            margin: 12px 0 0;
            display: grid;
            gap: 9px;
        }

        .decision dt {
            color: var(--ink);
            font-weight: 900;
            font-size: 13px;
        }

        .decision dd {
            margin: 2px 0 0;
            color: var(--muted);
        }

        .validation {
            display: grid;
            grid-template-columns: minmax(0, 1.08fr) minmax(320px, 0.92fr);
            gap: 22px;
        }

        .hypothesis {
            display: grid;
            gap: 12px;
        }

        .hypo-row {
            display: grid;
            grid-template-columns: 76px 1fr 160px;
            gap: 14px;
            align-items: start;
            padding: 16px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
        }

        .hypo-row b {
            color: var(--ink);
        }

        .hypo-row span,
        .hypo-row p {
            color: var(--muted);
            font-size: 14px;
        }

        .metric-board {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
            padding: 22px;
        }

        .metric-board h3 {
            font-size: 21px;
        }

        .reward-grid {
            margin-top: 18px;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }

        .reward {
            padding: 14px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #f8fafc;
        }

        .reward strong {
            display: block;
        }

        .reward span {
            display: block;
            margin-top: 4px;
            color: var(--muted);
            font-size: 13px;
        }

        .windows {
            margin-top: 20px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }

        .window {
            padding: 14px;
            border-radius: 8px;
            background: var(--ink);
            color: #fff;
        }

        .window strong {
            display: block;
            font-size: 21px;
        }

        .window span {
            display: block;
            margin-top: 4px;
            color: rgba(255, 255, 255, 0.72);
            font-size: 12px;
        }

        .result-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 18px;
        }

        .result-list {
            margin: 16px 0 0;
            padding: 0;
            list-style: none;
            display: grid;
            gap: 12px;
        }

        .result-list li {
            display: grid;
            grid-template-columns: 22px 1fr;
            gap: 10px;
            color: var(--muted);
        }

        .check {
            width: 18px;
            height: 18px;
            margin-top: 3px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--green-soft);
            color: var(--green);
            font-size: 12px;
            font-weight: 900;
        }

        .roadmap {
            margin-top: 24px;
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
        }

        .phase {
            position: relative;
            padding: 16px 14px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
        }

        .phase::after {
            content: "";
            position: absolute;
            right: -11px;
            top: 50%;
            width: 10px;
            height: 2px;
            background: var(--line-strong);
        }

        .phase:last-child::after {
            display: none;
        }

        .phase strong {
            display: block;
            color: var(--ink);
        }

        .phase span {
            display: block;
            margin-top: 6px;
            color: var(--muted);
            font-size: 13px;
        }

        .talk-track {
            display: grid;
            grid-template-columns: minmax(0, 0.72fr) minmax(320px, 0.48fr);
            gap: 24px;
            align-items: start;
        }

        .script-box {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #111827;
            color: #f9fafb;
            padding: 24px;
            box-shadow: var(--shadow);
        }

        .script-box p + p {
            margin-top: 14px;
        }

        .script-box strong {
            color: #93c5fd;
        }

        .footer {
            padding: 28px 24px 42px;
            color: var(--muted);
            text-align: center;
            border-top: 1px solid var(--line);
            background: var(--surface);
            font-size: 14px;
        }

        @media (max-width: 1080px) {
            .architecture,
            .validation,
            .talk-track {
                grid-template-columns: 1fr;
            }

            .arch-map {
                min-height: 590px;
            }

            .section-head {
                grid-template-columns: 1fr;
                gap: 18px;
            }

            .roadmap {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        @media (max-width: 960px) {
            .hero-grid {
                grid-template-columns: 1fr;
            }

            .product-visual {
                min-height: auto;
            }

            .flow-canvas {
                display: none;
            }

            .mock-system {
                min-height: auto;
                grid-template-columns: 0.78fr 1fr;
            }
        }

        @media (max-width: 820px) {
            .nav {
                align-items: flex-start;
                flex-direction: column;
                min-height: auto;
                padding: 14px 18px;
            }

            .hero-grid,
            .hero-grid > div {
                width: 100%;
                max-width: 100%;
            }

            .nowrap {
                white-space: normal;
            }

            .mobile-only {
                display: block;
            }

            h1 {
                width: calc(100vw - 48px);
                max-width: calc(100vw - 48px);
                font-size: 35px;
                line-height: 1.08;
                word-break: break-all;
            }

            .hero-copy {
                width: calc(100vw - 48px);
                font-size: 17px;
                max-width: calc(100vw - 48px);
                overflow-wrap: anywhere;
                word-break: break-all;
            }

            .nav-links {
                width: 100%;
                overflow-x: auto;
                padding-bottom: 2px;
            }

            .hero {
                padding-top: 38px;
            }

            .mock-system,
            .grid-3,
            .grid-2,
            .decision-grid,
            .result-grid {
                grid-template-columns: 1fr;
            }

            .product-visual,
            .mock-system,
            .phone,
            .dashboard,
            .dash-panel,
            .dash-stage,
            .output-panel {
                width: 100%;
                max-width: 100%;
                min-width: 0;
            }

            .agent-grid {
                grid-template-columns: 1fr;
            }

            .stage-row {
                grid-template-columns: 82px 1fr 54px;
            }

            .output-panel {
                grid-template-columns: 78px 1fr;
            }

            .hero-stats,
            .windows,
            .reward-grid {
                grid-template-columns: 1fr;
            }

            .map-table {
                display: block;
                overflow-x: auto;
                white-space: nowrap;
            }

            .hypo-row {
                grid-template-columns: 1fr;
            }

            .phone {
                min-height: auto;
            }

            .phone-screen {
                min-height: 380px;
            }

            .arch-map {
                min-height: auto;
                display: grid;
                gap: 12px;
            }

            .arch-map::before,
            .connector {
                display: none;
            }

            .node {
                position: static;
                width: auto;
            }

            .roadmap {
                grid-template-columns: 1fr;
            }

            .phase::after {
                display: none;
            }
        }

        @media print {
            .topbar,
            .hero-actions,
            .progress-rail {
                display: none;
            }

            body {
                background: #fff;
            }

            .section,
            .hero {
                padding: 34px 24px;
                min-height: auto;
                break-inside: avoid;
            }

            .card,
            .note,
            .metric-board,
            .script-box,
            .dash-panel,
            .dash-stage,
            .output-panel,
            .phone {
                box-shadow: none;
            }
        }
    </style>
</head>

<body>
    <header class="topbar">
        <nav class="nav" aria-label="主导航">
            <a class="brand" href="#top" aria-label="VideoClaw 首页">
                <span class="brand-mark">VC</span>
                <span>VideoClaw Product Strategy</span>
            </a>
            <div class="nav-links">
                <a href="#problem">需求</a>
                <a href="#product">设计</a>
                <a href="#architecture">架构</a>
                <a href="#decisions">决策</a>
                <a href="#validation">验证</a>
                <a href="#results">结果</a>
                <a href="#talk">总结</a>
            </div>
        </nav>
        <div class="progress-rail" aria-hidden="true">
            <div class="progress-bar" id="progressBar"></div>
        </div>
    </header>

    <main id="top">
        <section class="hero" data-section="top">
            <div class="hero-grid">
                <div>
                    <span class="eyebrow"><span class="dot"></span>多 Agent 短视频自动化生产系统</span>
                    <h1>把一句内容需求，<br>变成可发布、<br>可复盘、会进化的<br><span class="nowrap">短视频流水线。</span></h1>
                    <p class="hero-copy">
                        作为产品负责人，<br class="mobile-only">VideoClaw 被定义为<br class="mobile-only">“面向内容团队的 AI 内容操作系统”：<br class="mobile-only">
                        先降低从想法到成片的生产摩擦，<br class="mobile-only">再用抖音表现数据驱动下一轮内容决策。
                    </p>
                    <div class="hero-actions">
                        <a class="btn primary" href="#problem" aria-label="查看产品思路">↓ 查看产品思路</a>
                        <a class="btn" href="#talk" aria-label="查看汇报摘要">▶ 汇报摘要</a>
                    </div>
                    <div class="hero-stats" aria-label="核心概览">
                        <div class="stat">
                            <strong>10</strong>
                            <span>个专职 Agent，覆盖生产与反馈闭环</span>
                        </div>
                        <div class="stat">
                            <strong>6</strong>
                            <span>步主链路，从需求解析到发布交付</span>
                        </div>
                        <div class="stat">
                            <strong>3</strong>
                            <span>层系统底座：Agent、HTTP 服务、插件桥</span>
                        </div>
                    </div>
                </div>

                <div class="product-visual" aria-label="VideoClaw 产品运行视图">
                    <canvas class="flow-canvas" id="flowCanvas" width="760" height="680"></canvas>
                    <div class="mock-system">
                        <div class="phone" aria-label="飞书入口示意">
                            <div class="phone-screen">
                                <div class="phone-head">
                                    <span>Feishu Bot</span>
                                    <span>09:42</span>
                                </div>
                                <div class="chat user">请做一个 30 秒户外美食短视频，适合抖音发布。</div>
                                <div class="chat bot">已创建 run_id，并开始接地话题、调研热门素材、生成脚本与分镜。</div>
                                <div class="chat bot">发布前会在结果回传中给出标题、标签、视频文件和关键决策摘要。</div>
                                <div class="status-list">
                                    <div class="status-line">
                                        <span class="status-dot"></span>
                                        <span>Topic grounding</span>
                                        <strong>done</strong>
                                    </div>
                                    <div class="status-line">
                                        <span class="status-dot"></span>
                                        <span>Dual research</span>
                                        <strong>done</strong>
                                    </div>
                                    <div class="status-line">
                                        <span class="status-dot"></span>
                                        <span>Storyboard video</span>
                                        <strong>running</strong>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="dashboard">
                            <div class="dash-panel">
                                <div class="dash-title">
                                    <strong>Agent Control Room</strong>
                                    <span class="run-id">run_20260510_0942</span>
                                </div>
                                <div class="agent-grid">
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-blue">O</span>
                                        <span><b>orchestrator</b><span>创建状态主键</span></span>
                                    </div>
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-teal">T</span>
                                        <span><b>tag-matcher</b><span>话题接地</span></span>
                                    </div>
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-orange">R</span>
                                        <span><b>research</b><span>抖音 + 网页</span></span>
                                    </div>
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-violet">W</span>
                                        <span><b>writer</b><span>脚本分镜</span></span>
                                    </div>
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-rose">V</span>
                                        <span><b>video</b><span>并发生成拼接</span></span>
                                    </div>
                                    <div class="agent-chip">
                                        <span class="agent-icon bg-green">S</span>
                                        <span><b>stats</b><span>表现回流</span></span>
                                    </div>
                                </div>
                            </div>

                            <div class="dash-stage">
                                <div class="stage-track">
                                    <div class="stage-row">
                                        <strong>brief.json</strong>
                                        <span class="bar"><i style="width: 100%"></i></span>
                                        <span>完成</span>
                                    </div>
                                    <div class="stage-row">
                                        <strong>research</strong>
                                        <span class="bar"><i style="width: 92%; background: var(--blue)"></i></span>
                                        <span>可消费</span>
                                    </div>
                                    <div class="stage-row">
                                        <strong>script.json</strong>
                                        <span class="bar"><i style="width: 100%; background: var(--violet)"></i></span>
                                        <span>完成</span>
                                    </div>
                                    <div class="stage-row">
                                        <strong>video_result</strong>
                                        <span class="bar"><i style="width: 68%; background: var(--orange)"></i></span>
                                        <span>partial</span>
                                    </div>
                                </div>
                            </div>

                            <div class="output-panel">
                                <div class="video-tile" aria-hidden="true"></div>
                                <div>
                                    <div class="dash-title">
                                        <strong>可交付结果</strong>
                                        <span>publish gate</span>
                                    </div>
                                    <div class="metric-pills">
                                        <span>标题候选</span>
                                        <span>分镜脚本</span>
                                        <span>本地 MP4</span>
                                        <span>T+1h/T+24h/T+72h</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <section class="section" id="problem" data-section="problem">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">01 Demand Analysis</div>
                        <h2>需求不是“帮我生成视频”，而是“让我稳定产出有效内容”。</h2>
                    </div>
                    <p class="lead">
                        产品判断的起点是区分工具需求和业务需求：用户要的不是更多生成按钮，而是更低成本的内容试错、更高确定性的创作流程，以及发布后的复盘依据。
                    </p>
                </div>

                <div class="grid-3">
                    <article class="card">
                        <span class="label bg-blue">用户</span>
                        <h3>目标用户</h3>
                        <div class="persona">
                            <div class="persona-row">
                                <strong>轻量创作者</strong>
                                <span>缺团队、缺流程，希望把想法快速变成可发布内容。</span>
                            </div>
                            <div class="persona-row">
                                <strong>小型运营团队</strong>
                                <span>需要稳定周更/日更，关注效率、质量一致性和复盘。</span>
                            </div>
                            <div class="persona-row">
                                <strong>增长负责人</strong>
                                <span>关心内容是否能带来播放、互动、粉丝转化，而不只是“生成成功”。</span>
                            </div>
                        </div>
                    </article>

                    <article class="card">
                        <span class="label bg-orange">痛点</span>
                        <h3>核心问题</h3>
                        <p>短视频生产被拆成选题、找素材、看竞品、写脚本、生成视频、拼接、发布、复盘多个孤岛。</p>
                        <p>传统 AI 工具只能解决局部任务，无法回答“这条内容为什么值得做、做完怎么判断对不对”。</p>
                    </article>

                    <article class="card">
                        <span class="label bg-teal">北极星</span>
                        <h3>产品目标</h3>
                        <p class="thesis">提升“合格成片产出率”：用户给出一句需求后，系统能稳定交付可发布视频，并能解释关键决策。</p>
                        <p>辅助指标：首次成片时间、脚本采纳率、失败可恢复率、发布后留存/互动/转化分位。</p>
                    </article>
                </div>

                <div class="grid-2" style="margin-top: 18px;">
                    <article class="card plain">
                        <span class="label bg-violet">JTBD</span>
                        <h3>一句话用户任务</h3>
                        <p>当我只有一个模糊主题时，我希望系统帮我判断选题角度、参考热门内容、写出分镜并生成视频，这样我可以把时间花在内容判断和品牌表达上，而不是重复搬运流程。</p>
                    </article>
                    <article class="card plain">
                        <span class="label bg-green">优先级</span>
                        <h3>MVP 排序</h3>
                        <div class="priority-stack">
                            <div class="priority">
                                <span class="num">1</span>
                                <span><b>先打通端到端</b><span>一句需求到本地视频，比单点能力更能证明产品价值。</span></span>
                            </div>
                            <div class="priority">
                                <span class="num">2</span>
                                <span><b>再保证可恢复</b><span>视频生成慢且易失败，必须有状态主键、流式产物和完成门控。</span></span>
                            </div>
                            <div class="priority">
                                <span class="num">3</span>
                                <span><b>最后做数据闭环</b><span>没有发布与 reward 之前，不急着做复杂自进化。</span></span>
                            </div>
                        </div>
                    </article>
                </div>
            </div>
        </section>

        <section class="section alt" id="product" data-section="product">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">02 Product Translation</div>
                        <h2>把业务需求落到产品设计：每个体验动作都对应一个系统契约。</h2>
                    </div>
                    <p class="lead">
                        采用“业务目标 → 产品机制 → Agent/系统落点 → 判断理由”的映射方式管理需求，避免团队陷入“为了炫技而加 Agent”的陷阱。
                    </p>
                </div>

                <table class="map-table" aria-label="业务需求到产品设计映射">
                    <thead>
                        <tr>
                            <th>业务需求</th>
                            <th>产品设计</th>
                            <th>Agent / 系统落点</th>
                            <th>判断理由</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><b>低门槛启动</b><br>用户不想学习复杂工具链</td>
                            <td>飞书一句话入口、状态查询、结果回传</td>
                            <td>
                                <span class="tag">Feishu adapter</span>
                                <span class="tag">orchestrator</span>
                            </td>
                            <td>先把入口放到用户日常协作场景里，减少“打开新工具”的心理成本。</td>
                        </tr>
                        <tr>
                            <td><b>内容更贴近平台</b><br>脚本不能只靠模型想象</td>
                            <td>先做 topic grounding，再并发跑抖音与网页双通道调研</td>
                            <td>
                                <span class="tag">tag-matcher</span>
                                <span class="tag">research-supervisor</span>
                                <span class="tag">douyin-search</span>
                                <span class="tag">web-search</span>
                            </td>
                            <td>抖音负责“平台语感”，网页负责“事实与背景”，两者共同降低幻觉和离题。</td>
                        </tr>
                        <tr>
                            <td><b>交付完整成片</b><br>不能停在脚本文案</td>
                            <td>脚本、标题、标签、分镜、视频生成、拼接一体化</td>
                            <td>
                                <span class="tag">writer</span>
                                <span class="tag">video-generate</span>
                                <span class="tag">video_stitch</span>
                            </td>
                            <td>短视频价值在成片，不在 prompt。MVP 必须让用户看到最终物。</td>
                        </tr>
                        <tr>
                            <td><b>任务稳定可恢复</b><br>生成任务耗时长、外部服务不稳定</td>
                            <td>run_id 状态主键、结构化产物、partial + atomic rename、Completion gate</td>
                            <td>
                                <span class="tag">runs/&lt;run_id&gt;</span>
                                <span class="tag">STREAMING_PROTOCOL</span>
                                <span class="tag">RUN_LAYOUT</span>
                            </td>
                            <td>把“长任务”产品化，核心不是等得更久，而是让用户知道进度、失败点和可恢复路径。</td>
                        </tr>
                        <tr>
                            <td><b>越用越好</b><br>发布表现要能反哺下一轮</td>
                            <td>T+1h/T+24h/T+72h 数据回流，多目标 reward，按规则路由到对应 Agent</td>
                            <td>
                                <span class="tag">stats-collector</span>
                                <span class="tag">stats-analyzer</span>
                                <span class="tag">trace-critic</span>
                            </td>
                            <td>不做单一分数崇拜，用留存、转化、互动、长尾拆解具体责任，才能指导下一次决策。</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <section class="section" id="architecture" data-section="architecture">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">03 Agent Architecture</div>
                        <h2>Agent 架构不是组织图，而是产品职责边界图。</h2>
                    </div>
                    <p class="lead">
                        每个 Agent 只负责一个高价值判断，Orchestrator 管状态和门禁。这样既能并发，也能追责：哪一步影响了 retention、conversion 或 early burst，可以回到对应决策点。
                    </p>
                </div>

                <div class="architecture">
                    <div class="arch-map" aria-label="Agent 架构图">
                        <span class="connector c1"></span>
                        <span class="connector c2"></span>
                        <span class="connector c3"></span>
                        <span class="connector c4"></span>
                        <span class="connector c5"></span>
                        <span class="connector c6"></span>
                        <span class="connector c7"></span>
                        <span class="connector c8"></span>

                        <div class="node user"><small>input</small><b>用户一句需求</b></div>
                        <div class="node orch"><small>state owner</small><b>orchestrator</b></div>
                        <div class="node tag"><small>decision</small><b>tag-matcher</b></div>
                        <div class="node research"><small>coordinator</small><b>research-supervisor</b></div>
                        <div class="node writer"><small>creative</small><b>writer</b></div>
                        <div class="node douyin"><small>worker</small><b>douyin-search</b></div>
                        <div class="node web"><small>worker</small><b>web-search</b></div>
                        <div class="node video"><small>async</small><b>video-generate</b></div>
                        <div class="node publish"><small>gate</small><b>publisher</b></div>
                        <div class="node stats"><small>backward</small><b>stats + critic</b></div>
                    </div>

                    <div class="arch-notes">
                        <article class="note">
                            <h3><span class="label bg-blue" style="margin:0;">1</span> 三层系统底座</h3>
                            <ul>
                                <li>OpenClaw 多 Agent 负责判断、拆解和协作。</li>
                                <li>FastAPI 后端承接视频解析、分析、生成、拼接等重型能力。</li>
                                <li>TypeScript 插件把 Agent 工具调用转成安全 HTTP 能力边界。</li>
                            </ul>
                        </article>
                        <article class="note">
                            <h3><span class="label bg-teal" style="margin:0;">2</span> 状态设计</h3>
                            <ul>
                                <li><code>run_id</code> 是状态主键，Agent 之间不传大 payload。</li>
                                <li><code>brief.json</code>、<code>research_*.json</code>、<code>script.json</code>、<code>video_result.json</code> 形成可审计产物链。</li>
                                <li>流式产物用 <code>.partial</code> + 原子改名，消费者只读取终态 JSON。</li>
                            </ul>
                        </article>
                        <article class="note">
                            <h3><span class="label bg-orange" style="margin:0;">3</span> 反馈闭环</h3>
                            <ul>
                                <li>发布后由 stats 链路收集 T+1h、T+24h、T+72h 表现。</li>
                                <li>Reward 拆成 retention、conversion、engagement、viral、reach_quality。</li>
                                <li>Routing rules 把异常指标路由给最可能负责的 Agent。</li>
                            </ul>
                        </article>
                    </div>
                </div>
            </div>
        </section>

        <section class="section alt" id="decisions" data-section="decisions">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">04 Decisions</div>
                        <h2>关键产品决策：用取舍讲清楚为什么这样做。</h2>
                    </div>
                    <p class="lead">
                        产品方案的重点不只是“做了什么”，更是“为什么选择这个方案、放弃了什么、如何证明没有选错”。下面是五个关键决策。
                    </p>
                </div>

                <div class="decision-grid">
                    <article class="decision">
                        <span class="label bg-blue" style="margin:0;">D1</span>
                        <div>
                            <h3>多 Agent，而不是一个大 Prompt</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>短视频生产天然有多个专业角色：选题、调研、编剧、视频生成、发布复盘。拆开后才能并发、复用和归因。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>协作成本上升，状态同步复杂。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>看端到端成功率、失败定位时间、每个 Agent 产物是否可被下游稳定消费。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>

                    <article class="decision">
                        <span class="label bg-teal" style="margin:0;">D2</span>
                        <div>
                            <h3>结构化产物，而不是上下文传话</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>视频任务长、上下游多，靠对话上下文会丢信息；JSON 产物能审计、能恢复、能回放。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>Schema 维护成本增加。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>检查 <code>RUN_LAYOUT</code> 契约、Completion gate 回读、失败后 resume 能否继续。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>

                    <article class="decision">
                        <span class="label bg-orange" style="margin:0;">D3</span>
                        <div>
                            <h3>抖音 + 网页双通道调研</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>抖音给平台语感，网页给事实背景。只靠一种来源会在“爆款感”和“可信度”之间偏科。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>调研时间变长，信息噪声变多。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>脚本采纳率、事实错误率、人工评审分，以及 retain/drop 候选质量。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>

                    <article class="decision">
                        <span class="label bg-violet" style="margin:0;">D4</span>
                        <div>
                            <h3>Server-side wait，而不是 Agent 忙轮询</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>视频生成是异步长任务，让插件端等待能降低 token 和工具调用浪费。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>等待超时后的状态可见性要设计清楚。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>旧链路曾出现一次 38 次 polling；改造后用 <code>video_generate_wait_for_done</code> 收敛等待成本。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>

                    <article class="decision">
                        <span class="label bg-green" style="margin:0;">D5</span>
                        <div>
                            <h3>多目标 Reward，而不是一个总分</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>播放、留存、互动、转化不是同一件事。一个总分会掩盖“谁该改、改哪里”。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>早期样本少，统计结论不稳定。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>先按同类簇做 percentile，样本不足时只输出诊断，不自动改长期 playbook。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>

                    <article class="decision">
                        <span class="label bg-rose" style="margin:0;">D6</span>
                        <div>
                            <h3>发布门禁，而不是全自动无确认</h3>
                            <dl>
                                <div>
                                    <dt>为什么</dt>
                                    <dd>发布是外部平台的真实操作，必须给用户保留最后确认权，避免错误内容直接出街。</dd>
                                </div>
                                <div>
                                    <dt>风险</dt>
                                    <dd>自动化链路被人工确认打断。</dd>
                                </div>
                                <div>
                                    <dt>验证</dt>
                                    <dd>看确认率、退回修改原因、发布失败率，把“需要人判断”的点沉淀成下次自动决策。</dd>
                                </div>
                            </dl>
                        </div>
                    </article>
                </div>
            </div>
        </section>

        <section class="section" id="validation" data-section="validation">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">05 Validation</div>
                        <h2>验证不是等上线后看播放量，而是为每个判断提前埋好证据链。</h2>
                    </div>
                    <p class="lead">
                        我的验证思路分两层：先证明流程能稳定跑完，再证明不同 Agent 的决策确实影响内容结果。前者看工程健康度，后者看平台 reward 和人工评审。
                    </p>
                </div>

                <div class="validation">
                    <div class="hypothesis">
                        <div class="hypo-row">
                            <b>假设 H1</b>
                            <p>一句自然语言需求可以稳定生成可发布成片。</p>
                            <span>端到端成功率、首次成片时间、失败阶段分布</span>
                        </div>
                        <div class="hypo-row">
                            <b>假设 H2</b>
                            <p>接地 + 双通道调研能让脚本更贴近平台和事实。</p>
                            <span>脚本采纳率、事实错误率、人工脚本评分</span>
                        </div>
                        <div class="hypo-row">
                            <b>假设 H3</b>
                            <p>超过 30 秒的视频，storyboard 生成比 single shot 更利于留存。</p>
                            <span>同类簇 retention_pct、shot_avg_duration 切片</span>
                        </div>
                        <div class="hypo-row">
                            <b>假设 H4</b>
                            <p>发布时间、标题和 hashtag 会显著影响早期推荐。</p>
                            <span>early_burst_ratio、reach_quality_pct、publish_hour 切片</span>
                        </div>
                    </div>

                    <aside class="metric-board" aria-label="Reward 验证设计">
                        <h3>Reward 观测框架</h3>
                        <p class="lead" style="font-size: 15px; margin-top: 8px;">
                            每条已发布视频进入 episode，按时间窗补齐平台数据，再放入同类簇里做横向分位。
                        </p>
                        <div class="windows">
                            <div class="window">
                                <strong>T+1h</strong>
                                <span>早期推荐推力</span>
                            </div>
                            <div class="window">
                                <strong>T+24h</strong>
                                <span>主分发稳定态</span>
                            </div>
                            <div class="window">
                                <strong>T+72h</strong>
                                <span>长尾与搜索流量</span>
                            </div>
                        </div>
                        <div class="reward-grid">
                            <div class="reward">
                                <strong>retention</strong>
                                <span>completion × 非 2 秒跳出</span>
                            </div>
                            <div class="reward">
                                <strong>conversion</strong>
                                <span>净涨粉 / 播放</span>
                            </div>
                            <div class="reward">
                                <strong>engagement</strong>
                                <span>赞评转藏 / 播放</span>
                            </div>
                            <div class="reward">
                                <strong>viral</strong>
                                <span>T+72h / T+24h</span>
                            </div>
                            <div class="reward">
                                <strong>reach_quality</strong>
                                <span>非粉播放占比</span>
                            </div>
                            <div class="reward">
                                <strong>routing</strong>
                                <span>异常指标 → 对应 Agent</span>
                            </div>
                        </div>
                    </aside>
                </div>
            </div>
        </section>

        <section class="section alt" id="results" data-section="results">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">06 Results & Roadmap</div>
                        <h2>结果要诚实：哪些已经证明，哪些还只是下一阶段假设。</h2>
                    </div>
                    <p class="lead">
                        项目结果需要呈现清晰边界：已落地的是自动化生产和鲁棒性，待验证的是真实平台 reward 驱动的持续优化。
                    </p>
                </div>

                <div class="result-grid">
                    <article class="card">
                        <span class="label bg-green">已落地</span>
                        <h3>端到端生产链路</h3>
                        <ul class="result-list">
                            <li><span class="check">✓</span><span>Feishu 入口到 orchestrator 的任务启动路径。</span></li>
                            <li><span class="check">✓</span><span>选题接地、双通道调研、脚本分镜、视频生成、拼接的 6 步主链路。</span></li>
                            <li><span class="check">✓</span><span>FastAPI 后端与 video-http-tools 插件桥接重型能力。</span></li>
                        </ul>
                    </article>

                    <article class="card">
                        <span class="label bg-blue">已强化</span>
                        <h3>长任务可靠性</h3>
                        <ul class="result-list">
                            <li><span class="check">✓</span><span><code>run_id</code> 统一状态主键，所有产物进入 runs 目录。</span></li>
                            <li><span class="check">✓</span><span>partial + atomic rename 避免下游读取半成品。</span></li>
                            <li><span class="check">✓</span><span>Completion gate 回读终态产物，降低 silent failure。</span></li>
                        </ul>
                    </article>

                    <article class="card">
                        <span class="label bg-orange">待验证</span>
                        <h3>数据驱动进化</h3>
                        <ul class="result-list">
                            <li><span class="check">✓</span><span>5 层记忆模型和 playbook 入口已经设计好。</span></li>
                            <li><span class="check">✓</span><span>Reward、routing rules、trace-critic 的设计文档已成型。</span></li>
                            <li><span class="check">✓</span><span>需要继续打通 publish_result → episode → stats join。</span></li>
                        </ul>
                    </article>
                </div>

                <div class="roadmap" aria-label="实施路线图">
                    <div class="phase">
                        <strong>Phase A</strong>
                        <span>发布结果持久化，解析 aweme_id，初始化 episode。</span>
                    </div>
                    <div class="phase">
                        <strong>Phase B</strong>
                        <span>聚合 T+1h/T+24h/T+72h 平台表现，写 reward。</span>
                    </div>
                    <div class="phase">
                        <strong>Phase C</strong>
                        <span>Stat-attributor 做规则切片，生成强证据 playbook。</span>
                    </div>
                    <div class="phase">
                        <strong>Phase D</strong>
                        <span>Trace-critic 只分析 outlier，输出自然语言归因。</span>
                    </div>
                    <div class="phase">
                        <strong>Phase E</strong>
                        <span>样本足够后做 GEPA-style prompt evolution。</span>
                    </div>
                </div>
            </div>
        </section>

        <section class="section" id="talk" data-section="talk">
            <div class="wrap">
                <div class="section-head">
                    <div>
                        <div class="kicker">07 Executive Summary</div>
                        <h2>汇报摘要：先定义问题，再解释架构，最后说明验证路径。</h2>
                    </div>
                    <p class="lead">
                        以下内容用于快速呈现产品判断、方案取舍与验证逻辑，帮助评审在短时间内把握项目重点。
                    </p>
                </div>

                <div class="talk-track">
                    <div class="script-box">
                        <p><strong>项目定位：</strong>VideoClaw 不是一个单纯的视频生成 demo，而是面向内容团队的 AI 内容操作系统。它解决的是“从一个模糊选题到可发布短视频”的整条链路，而不是某个生成按钮。</p>
                        <p><strong>需求判断：</strong>用户真正的痛点有三个：生产链路割裂、内容判断依赖直觉、发布后数据不能回流。因此 MVP 优先级是先打通端到端，再解决长任务可靠性，最后引入数据闭环。</p>
                        <p><strong>方案设计：</strong>系统采用多 Agent 架构，因为短视频生产天然对应多个专业角色。Orchestrator 只做状态和门禁，tag-matcher 负责接地，research 负责证据，writer 负责脚本，video-generate 负责异步生成，publisher 和 stats 链路负责发布与反馈。</p>
                        <p><strong>验证方式：</strong>验证口径不止“生成成功”。第一层看端到端成功率、首次成片时间、失败可恢复率；第二层看发布后的 retention、conversion、engagement、viral、reach_quality，并用 routing rules 把问题回到具体 Agent 决策点。</p>
                        <p><strong>结果边界：</strong>当前已经证明的是主链路和鲁棒性设计，数据闭环的壳和指标体系已经设计好；下一步要补的是 publish_result 到 episode 的关联链路，以及真实样本积累后的归因验证。</p>
                    </div>

                    <aside class="card">
                        <span class="label bg-violet">讨论要点</span>
                        <h3>关键问题回应</h3>
                        <ul class="talk-list">
                            <li><b>为什么不用一个 Agent？</b><br>因为职责不可归因，失败后不知道该改选题、脚本还是视频生成。</li>
                            <li><b>冷启动没有数据怎么办？</b><br>前期用人工评审 + trace-critic，样本不足时只做建议，不自动改长期 playbook。</li>
                            <li><b>怎么衡量生成质量？</b><br>先看可交付，再看平台表现；内容质量拆成留存、互动、转化、长尾，不压成单分数。</li>
                            <li><b>商业化价值在哪？</b><br>降低内容团队试错成本，让稳定产出和复盘成为可复制流程。</li>
                        </ul>
                    </aside>
                </div>
            </div>
        </section>
    </main>

    <footer class="footer">
        VideoClaw Product Strategy · 需求分析、产品设计、Agent 架构、验证指标与结果边界
    </footer>

    <script>
        const progressBar = document.getElementById("progressBar");
        const links = Array.from(document.querySelectorAll(".nav-links a"));
        const sections = Array.from(document.querySelectorAll("[data-section]"));

        function updateProgress() {
            const scrollTop = window.scrollY || document.documentElement.scrollTop;
            const height = document.documentElement.scrollHeight - window.innerHeight;
            const progress = height > 0 ? (scrollTop / height) * 100 : 0;
            progressBar.style.width = `${progress}%`;
        }

        const observer = new IntersectionObserver((entries) => {
            const visible = entries
                .filter((entry) => entry.isIntersecting)
                .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];

            if (!visible) return;
            const id = visible.target.id || "top";
            links.forEach((link) => {
                const target = link.getAttribute("href").replace("#", "");
                link.classList.toggle("active", target === id);
            });
        }, { rootMargin: "-35% 0px -55% 0px", threshold: [0.05, 0.2, 0.5] });

        sections.forEach((section) => observer.observe(section));
        window.addEventListener("scroll", updateProgress, { passive: true });
        updateProgress();

        const canvas = document.getElementById("flowCanvas");
        const ctx = canvas ? canvas.getContext("2d") : null;
        const pulses = [
            { path: [[78, 338], [270, 126], [520, 126], [668, 336]], color: "#2563eb", speed: 0.0026, offset: 0 },
            { path: [[120, 444], [340, 280], [560, 310], [660, 472]], color: "#0f766e", speed: 0.0022, offset: 0.36 },
            { path: [[392, 528], [500, 568], [658, 526]], color: "#ea580c", speed: 0.0024, offset: 0.68 }
        ];

        function pointOnPath(path, t) {
            const lengths = [];
            let total = 0;
            for (let i = 0; i < path.length - 1; i++) {
                const [x1, y1] = path[i];
                const [x2, y2] = path[i + 1];
                const len = Math.hypot(x2 - x1, y2 - y1);
                lengths.push(len);
                total += len;
            }
            let target = t * total;
            for (let i = 0; i < lengths.length; i++) {
                if (target <= lengths[i]) {
                    const [x1, y1] = path[i];
                    const [x2, y2] = path[i + 1];
                    const local = target / lengths[i];
                    return [x1 + (x2 - x1) * local, y1 + (y2 - y1) * local];
                }
                target -= lengths[i];
            }
            return path[path.length - 1];
        }

        function drawFlow(time) {
            if (!ctx || window.matchMedia("(max-width: 1080px)").matches) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.lineWidth = 1.4;
            pulses.forEach((pulse) => {
                ctx.beginPath();
                pulse.path.forEach(([x, y], index) => {
                    if (index === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                });
                ctx.strokeStyle = "rgba(102, 112, 133, 0.22)";
                ctx.stroke();

                const t = (time * pulse.speed + pulse.offset) % 1;
                const [x, y] = pointOnPath(pulse.path, t);
                ctx.beginPath();
                ctx.arc(x, y, 5.5, 0, Math.PI * 2);
                ctx.fillStyle = pulse.color;
                ctx.fill();
                ctx.beginPath();
                ctx.arc(x, y, 13, 0, Math.PI * 2);
                ctx.strokeStyle = pulse.color + "55";
                ctx.stroke();
            });
            requestAnimationFrame(drawFlow);
        }

        if (ctx) requestAnimationFrame(drawFlow);
    </script>
</body>

</html>
ing presentation.html…]()


你只需要在飞书里发送一句视频需求，VideoClaw 会自动完成选题接地、热门内容调研、脚本撰写、分镜视频生成、自动拼接、结果回传，并可继续接入抖音发布与数据复盘。

> 一句话概括：把“我想做一条短视频”到“成片可发布”之间的琐碎流程，交给一组专职 Agent 协同完成。

---

## 核心能力

- **多 Agent 流水线**：orchestrator 统一调度 tag-matcher、research-supervisor、writer、video-generate、publisher 等专职 Agent。
- **双通道调研**：同时结合抖音候选视频与网页资料，为脚本生成提供内容依据。
- **脚本与分镜生成**：生成标题、旁白、镜头描述、标签和多分镜 storyboard。
- **视频生成与拼接**：支持 MiniMax Hailuo、字节跳动 Seedance/Ark 等视频生成服务；多分镜可并行生成并通过 ffmpeg 自动拼接。
- **发布与反馈闭环**：可接入抖音创作者中心发布，并通过 stats collector/analyzer 跟踪表现数据，反哺下一轮内容生产。
- **本地可调试**：FastAPI 后端提供健康检查、任务状态查询、视频生成、转写、分析、标签检索等 HTTP API。

---

## Demo

示例输入：

```text
请你给我做一个户外美食相关的30秒左右的视频
```

示例流水线：

```text
tag-matcher
  -> research-supervisor
     -> douyin-search
     -> web-search
  -> writer
  -> video-generate
  -> publisher
```

## 系统架构
<img width="1024" height="559" alt="videoagent框架" src="https://github.com/user-attachments/assets/2fd8c86a-822b-4cff-b2c2-afe68cd66dee" />


VideoClaw 由三层组成：

### 1. OpenClaw 多 Agent 流水线

```text
用户请求
  -> orchestrator          总协调，创建 run_id 并推进流程
  -> tag-matcher           将宽泛话题接地为可检索、可创作的具体标签
  -> research-supervisor   规划调研任务，并发调度子 Agent
     -> douyin-search      检索抖音候选视频
     -> web-search         搜集网页背景资料
  -> writer                生成完整脚本、分镜、旁白、标题和标签
  -> video-generate        调用视频生成服务，等待异步任务完成并拼接
  -> publisher             可选：发布到抖音创作者中心
```

流水线通过 `run_id` 共享状态。每次任务会在 OpenClaw runs 目录中生成一组结构化产物，例如：

```text
runs/<run_id>/
  brief.json
  research_douyin.json
  research_web.json
  script.json
  video_result.json
  publish_result.json
```

### 2. 外部 HTTP 服务（`agent-service/`）

`agent-service` 是一个 Python FastAPI 后端，为 OpenClaw 插件提供重型能力：

- 抖音视频解析、下载与清理
- Gemini 视频分析与音频转写
- MiniMax / Seedance 视频生成
- 多分镜视频拼接
- 标签知识库查询
- 视频表现数据存储与查询
- 飞书机器人事件回调与任务状态观察

服务启动后可访问：

```text
GET  /health
GET  /docs
GET  /runs
GET  /runs/{run_id}/status
POST /webhooks/feishu/events
```

### 3. OpenClaw 插件（`openclaw-plugins/video-http-tools/`）

TypeScript 插件负责把 OpenClaw Tool 调用转发到 FastAPI：

- `tag_get_script_pack`
- `media_resolve_video`
- `media_fetch_video`
- `video_analyze_start`
- `transcribe_start`
- `video_generate_start`
- `video_generate_wait_for_done`
- `video_stitch`
- `stats_query`
- `stats_writer`

---

## 项目结构

```text
.
├── agent-service/                  # FastAPI 后端服务
│   ├── app/
│   │   ├── routes/                 # HTTP 路由
│   │   ├── services/               # 业务服务
│   │   ├── providers/              # Gemini、MiniMax、Seedance、Douyin 等 provider
│   │   ├── schemas/                # Pydantic 请求/响应模型
│   │   └── adapters/               # 飞书等消息适配器
│   ├── video-agent-system/         # 抖音采集与标签知识库构建工具
│   ├── requirements.txt
│   └── .env.example
│
├── openclaw-plugins/
│   └── video-http-tools/           # OpenClaw HTTP 工具插件
│
├── workspace-orchestrator/         # 总协调 Agent
├── workspace-tag-matcher/          # 标签接地 Agent
├── workspace-research-supervisor/  # 调研协调 Agent
├── workspace-douyin-search/        # 抖音检索 Agent
├── workspace-web-search/           # 网页检索 Agent
├── workspace-writer/               # 脚本写作 Agent
├── workspace-video-generate/       # 视频生成 Agent
├── workspace-publisher/            # 发布 Agent
├── workspace-stats-collector/      # 数据采集 Agent
├── workspace-stats-analyzer/       # 数据分析 Agent
│
├── docs/                           # 架构、协议、调试文档
├── cron/                           # 定时任务配置
├── pics/                           # README 与文档图片
├── openclaw.example.json           # OpenClaw 配置模板
└── setup.sh                        # 生成 openclaw.json 的初始化脚本
```

---
## 飞书机器人入口

飞书入口由 `agent-service` 直接接收事件，然后把标准化后的消息交给 OpenClaw orchestrator。

### 1. 创建飞书自建应用

在飞书开放平台创建企业自建应用，并记录：

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
```

### 2. 配置回调

FastAPI 回调地址：

```text
POST /webhooks/feishu/events
```

本地开发可用 ngrok 或 cloudflared 暴露：

```bash
ngrok http 8000
```

然后在飞书开放平台事件订阅中填写：

```text
https://你的公网地址/webhooks/feishu/events
```

### 3. 启用飞书配置

在 `agent-service/.env` 中设置：

```bash
FEISHU_BOT_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx

OPENCLAW_ORCHESTRATOR_COMMAND="openclaw agents spawn orchestrator"
OPENCLAW_RUNS_ROOT=~/.openclaw/runs
OPENCLAW_START_MODE=cli
FEISHU_RESULT_WATCH_TIMEOUT_SEC=3600
FEISHU_RESULT_WATCH_INTERVAL_SEC=10
```

飞书内可用命令：

```text
/status <run_id>
/runs
```

更多细节见 [docs/FEISHU_ADAPTER.md](docs/FEISHU_ADAPTER.md)。

---



## 数据反馈闭环

VideoClaw 的长期目标不是只跑完一次生成，而是通过每条视频的表现数据不断改进内容策略。

```text
已发布视频
  -> stats-collector   定期采集播放、点赞、评论、分享、收藏等指标
  -> stats-analyzer    生成周报与内容建议
  -> orchestrator      在下一次选题、脚本与分镜决策中参考历史反馈
```

相关 Agent：

- `workspace-stats-collector/`
- `workspace-stats-analyzer/`

相关文档：

- [docs/BACKWARD_ROUTING.md](docs/BACKWARD_ROUTING.md)
- [docs/BACKWARD_REWARD.md](docs/BACKWARD_REWARD.md)
- [docs/BACKWARD_OPS.md](docs/BACKWARD_OPS.md)

---

## 重要文档

- [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)：系统总览与阶段规划
- [docs/PIPELINE.md](docs/PIPELINE.md)：主流水线说明
- [docs/RUN_LAYOUT.md](docs/RUN_LAYOUT.md)：任务运行目录结构
- [docs/STREAMING_PROTOCOL.md](docs/STREAMING_PROTOCOL.md)：流式写入与恢复协议
- [docs/ASYNC_JOBS.md](docs/ASYNC_JOBS.md)：异步任务协议
- [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md)：本地开发调试
- [docs/FEISHU_ADAPTER.md](docs/FEISHU_ADAPTER.md)：飞书机器人接入
- [docs/BROWSER.md](docs/BROWSER.md)：Windows 浏览器节点与抖音发布
- [agent-service/API_documents.txt](agent-service/API_documents.txt)：后端 API 说明
- [agent-service/video-agent-system/tag_knowledge_db/README.md](agent-service/video-agent-system/tag_knowledge_db/README.md)：标签知识库构建

---


## Roadmap

- 完善发布后数据采集与指标归因
- 强化 weekly insight 对下一轮脚本和分镜的影响
- 支持更多视频生成 provider
- 增强飞书交互卡片与任务状态展示
- 补充端到端示例与部署脚本






