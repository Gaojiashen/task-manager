import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from './App';
import {CrowWidget} from './CrowWidget';
import './crow-widget.css';
import './style.css';
import './tools.css';
import './canvas-sync.css';
import './canvas-reader.css';
const widget = new URLSearchParams(window.location.search).get('widget') === '1';
if (widget) document.documentElement.classList.add('crow-widget-mode');
createRoot(document.getElementById('root')!).render(<React.StrictMode>{widget ? <CrowWidget/> : <App/>}</React.StrictMode>);

import './mail.css';

import './mail-workspace.css';
