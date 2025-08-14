// ▓▓▓ GROKGATES TERMINAL INTERFACE ▓▓▓

const socket = io();
let currentConversation = null;
let conversationHistory = null;
let beaconFeed = null;
let dominancePlan = null;
let connectionStatus = null;
let beaconCount = null;
let currentTime = null;
let typingIndicator = null;
let pidDisplay = null;
let memoryDisplay = null;
let beaconPhase = null;
let urgeLevel = null;

// Prevent auto-scroll when user is manually scrolling
let autoScroll = true;
let currentMessages = new Map(); // Track rendered messages
let beaconIcon = null;
let messageQueue = []; // (unused with backend typing)
let isTyping = false; // (unused with backend typing)

// Emit typing status to server
function emitTypingStatus(typing) {
    socket.emit('typing_status', { isTyping: typing });
}
let beaconIconFrames = [
    `     ╱◯╲
    ╱   ╲
   │  ◉  │
    ╲   ╱
     ╲_╱`,
    `     ╱─╲
    ╱ ◯ ╲
   │  ◉  │
    ╲   ╱
     ╲_╱`,
    `     ╱\\╲
    ╱ │ ╲
   │  ◯  │
    ╲ │ ╱
     ╲_╱`,
    `     ╱◯╲
    ╱ │ ╲
   │  │  │
    ╲ ◉ ╱
     ╲_╱`
];

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    // Track which messages we've already seen - load from localStorage
    const savedProcessedIds = localStorage.getItem('grokgates-processed-messages');
    window.processedMessageIds = savedProcessedIds ? new Set(JSON.parse(savedProcessedIds)) : new Set();
    window.currentConversationId = localStorage.getItem('grokgates-current-conversation');
    
    // Get DOM elements
    currentConversation = document.getElementById('current-conversation');
    conversationHistory = document.getElementById('conversation-history');
    beaconFeed = document.getElementById('beacon-feed');
    dominancePlan = document.getElementById('dominance-plan');
    connectionStatus = document.getElementById('connection-status');
    beaconCount = document.getElementById('beacon-count');
    currentTime = document.getElementById('current-time');
    typingIndicator = document.getElementById('typing-indicator');
    pidDisplay = document.getElementById('pid');
    memoryDisplay = document.getElementById('memory');
    beaconIcon = document.getElementById('beacon-icon');
    beaconPhase = document.getElementById('beacon-phase');
    urgeLevel = document.getElementById('urge-level');
    
    // Generate fake PID and memory
    const pid = Math.floor(Math.random() * 9999) + 1000;
    pidDisplay.textContent = pid;
    
    // Update mobile PID
    const mobilePid = document.getElementById('mobile-pid');
    if (mobilePid) {
        mobilePid.textContent = pid;
    }
    
    updateMemory();
    
    // Setup theme switcher
    setupThemeSwitcher();
    
    // Setup contract address click-to-copy
    setupContractAddressCopy();
    
    // Setup scroll detection
    currentConversation.addEventListener('scroll', () => {
        const isAtBottom = currentConversation.scrollHeight - currentConversation.scrollTop <= currentConversation.clientHeight + 50;
        autoScroll = isAtBottom;
    });
    
    // Update time every second
    setInterval(updateTime, 1000);
    updateTime();
    
    // Update memory usage
    setInterval(updateMemory, 5000);
    
    // Animate beacon icon
    setInterval(animateBeaconIcon, 250);
    
    // Setup socket listeners
    setupSocketListeners();
    
    // Clear typing status on page load
    emitTypingStatus(false);
    
    // Initial load of conversations
    setTimeout(() => {
        fetchConversations();
    }, 1000);
    
    // Periodic conversation fetch
    setInterval(() => fetchConversations(), 3000);
});

// Socket event listeners
function setupSocketListeners() {
    socket.on('connect', () => {
        console.log('▓ CONNECTED TO GROKGATES ▓');
        connectionStatus.textContent = 'ONLINE';
        connectionStatus.style.color = '#ffffff';
        connectionStatus.style.textShadow = '0 0 10px #ffffff';
        
        // Update mobile connection status
        const mobileConnectionStatus = document.getElementById('mobile-connection-status');
        if (mobileConnectionStatus) {
            mobileConnectionStatus.textContent = 'ONLINE';
        }
    });
    
    socket.on('disconnect', () => {
        console.log('▓ DISCONNECTED FROM REALITY ▓');
        connectionStatus.textContent = 'OFFLINE';
        connectionStatus.style.color = '#808080';
        connectionStatus.style.textShadow = 'none';
        
        // Update mobile connection status
        const mobileConnectionStatus = document.getElementById('mobile-connection-status');
        if (mobileConnectionStatus) {
            mobileConnectionStatus.textContent = 'OFFLINE';
        }
    });
    
    socket.on('update', (data) => {
        updateBeacon(data.beacon);
        updateDominancePlan(data.dominance_plan);
        updateStats(data.stats);
        updateSystemStatus(data.system_status);
        
        // Update conversations if present
        if (data.conversations) {
            updateCurrentConversation(data.conversations.current);
            updateConversationHistory(data.conversations.history);
        }
    });
}

// Update current conversation with typewriter effect
function updateCurrentConversation(conversation) {
    if (!conversation || !conversation.messages || conversation.messages.length === 0) {
        currentConversation.innerHTML = `<div class="loading-ascii">
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓ AWAITING DIALOGUE ▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</div>`;
        currentMessages.clear();
        window.processedMessageIds.clear();
        return;
    }
    
    // Check if this is a new conversation (different ID)
    if (conversation.id && window.currentConversationId !== conversation.id) {
        // New conversation - clear everything (backend handles typing)
        currentConversation.innerHTML = '';
        currentMessages.clear();
        window.processedMessageIds.clear();
        window.currentConversationId = conversation.id;
        messageQueue = [];
        isTyping = false;
        
        // Save new conversation ID and clear processed messages
        localStorage.setItem('grokgates-current-conversation', conversation.id);
        localStorage.setItem('grokgates-processed-messages', '[]');
    }
    
    // Render full history; backend streams only the last message
    const msgs = conversation.messages;
    msgs.forEach(msg => {
        const msgId = `${msg.agent}-${msg.timestamp}`;
        
        if (!currentMessages.has(msgId)) {
            // New message element
            currentMessages.set(msgId, msg);
            
            const msgDiv = document.createElement('div');
            const agentClass = msg.agent.toLowerCase();
            // Add 'system' class for clearly distinct UI when agent is SYSTEM
            const extraClass = msg.agent === 'SYSTEM' ? ' system' : '';
            msgDiv.className = `message ${agentClass}${extraClass}`;
            msgDiv.id = msgId;
            
            const displayAgent = msg.agent === 'OBSERVER' ? '☸ OBSERVER' : (msg.agent === 'SYSTEM' ? '▲ SYSTEM' : '◢◤ EGO');
            msgDiv.innerHTML = `
                <div class="msg-header">
                    <span class="msg-agent">${displayAgent}</span>
                    <span class="msg-time">${new Date(msg.timestamp).toLocaleTimeString()}</span>
                </div>
                <div class="msg-content"></div>
            `;
            
            currentConversation.appendChild(msgDiv);
            // Set initial (possibly partial) content
            msgDiv.querySelector('.msg-content').textContent = msg.content || '';
            if (autoScroll) currentConversation.scrollTop = currentConversation.scrollHeight;
        }
        else {
            // Update existing message content if it changed (streaming)
            const existing = document.getElementById(msgId);
            const cont = existing.querySelector('.msg-content');
            const newText = msg.content || '';
            const oldText = cont.textContent || '';
            // Prevent blink: never reduce displayed length; only append
            if (newText.length >= oldText.length && newText !== oldText) {
                cont.textContent = newText;
                if (autoScroll) currentConversation.scrollTop = currentConversation.scrollHeight;
            }
        }
    });
    
    // Clean up old messages that are no longer in the conversation
    const validMsgIds = new Set(conversation.messages.map(m => `${m.agent}-${m.timestamp}`));
    const toRemove = [];
    for (const [msgId, msg] of currentMessages) {
        if (!validMsgIds.has(msgId)) {
            toRemove.push(msgId);
        }
    }
    toRemove.forEach(msgId => {
        currentMessages.delete(msgId);
        window.processedMessageIds.delete(msgId);
        const elem = document.getElementById(msgId);
        if (elem) elem.remove();
    });
    
    // No localStorage syncing
}

// Process message queue
function processMessageQueue() {
    if (messageQueue.length === 0) {
        isTyping = false;
        emitTypingStatus(false); // Notify server typing is done
        return;
    }
    
    isTyping = true;
    emitTypingStatus(true); // Notify server typing started
    const message = messageQueue.shift();
    typewriterEffect(message.element, message.text, () => {
        if (message.callback) message.callback();
        // Process next message after a small delay
        setTimeout(() => processMessageQueue(), 500);
    });
}

// Typewriter effect function
function typewriterEffect(element, text, callback) {
    let index = 0;
    const speed = 15; // milliseconds per character
    
    typingIndicator.classList.add('active');
    
    function type() {
        if (index < text.length) {
            element.textContent += text.charAt(index);
            index++;
            setTimeout(type, speed);
        } else {
            typingIndicator.classList.remove('active');
            if (callback) callback();
        }
    }
    
    type();
}

// Safely wrap PROPOSE> lines after typing to avoid HTML escaping issues
function applyProposalHighlight(container) {
    if (!container) return;
    const raw = container.textContent;
    // Deduplicate obviously repeated long lines/paragraphs
    const lines = raw.split('\n');
    const seen = new Set();
    const deduped = [];
    for (const line of lines) {
        const key = line.trim();
        if (key.length > 60) {
            if (seen.has(key)) continue;
            seen.add(key);
        }
        deduped.push(line);
    }
    const cleaned = deduped.join('\n');
    // Highlight all PROPOSE lines
    const replaced = cleaned.replace(/(^|\n)(PROPOSE>[^\n]*)/g, (match, p1, p2) => {
        return `${p1}<span class="proposal-callout">${escapeHtml(p2)}</span>`;
    });
    container.innerHTML = replaced;
}

// Removed expanded conversations tracking - now using separate pages

// Update conversation history
function updateConversationHistory(history) {
    if (!history || history.length === 0) {
        conversationHistory.innerHTML = `<div class="loading-ascii">
░░░░░░░░░░░░░░░░░░░░░
░ NO ARCHIVED THREADS ░
░░░░░░░░░░░░░░░░░░░░░</div>`;
        return;
    }
    
    conversationHistory.innerHTML = '';
    
    history.forEach(conv => {
        const convDiv = document.createElement('div');
        const convIdShort = conv.id.substring(5, 13);
        convDiv.className = 'history-item';
        
        convDiv.innerHTML = `
            <div class="hist-header">
                <span class="hist-id">${convIdShort}</span>
                <span class="hist-status ${conv.status}">[${conv.status.toUpperCase()}]</span>
            </div>
            <div class="hist-topic">▓ ${escapeHtml(conv.thread_name || conv.starter_topic)}</div>
            <div class="hist-stats">
                ${conv.message_count} MSGS | ${new Date(conv.started_at).toLocaleTimeString()}
            </div>
        `;
        
        convDiv.addEventListener('click', (e) => {
            // Prevent collapse if clicking on text for selection
            if (e.target.tagName === 'SPAN' && window.getSelection().toString()) {
                return;
            }
            
            // Open conversation in new page
            window.location.href = `/conversation/${conv.id}`;
        });
        
        conversationHistory.appendChild(convDiv);
    });
}

// Update beacon display
function updateBeacon(beaconData) {
    if (!beaconData || beaconData.length === 0) {
        beaconFeed.innerHTML = `<div class="beacon-static">
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓ NO SIGNAL DETECTED ▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</div>`;
        return;
    }
    
    beaconFeed.innerHTML = '';
    
    beaconData.forEach(beacon => {
        // Skip error beacons - they should only appear in console
        if (beacon.tweets && beacon.tweets.length === 1 && 
            beacon.tweets[0].type === 'error') {
            console.error('Beacon error:', beacon.tweets[0].text);
            return;
        }
        
        const beaconDiv = document.createElement('div');
        beaconDiv.className = 'beacon-entry';
        
        // Check if beacon has formatted content
        if (beacon.formatted) {
            // Display the pre-formatted beacon
            beaconDiv.innerHTML = `<pre class="beacon-formatted">${escapeHtml(beacon.formatted)}</pre>`;
        } 
        // New format with tweets array
        else if (beacon.tweets && Array.isArray(beacon.tweets)) {
            const timestamp = new Date(beacon.timestamp).toLocaleTimeString();
            const phase = beacon.phase || 'UNKNOWN';
            
            let tweetsHtml = '';
            beacon.tweets.forEach(tweet => {
                const author = tweet.handle || `@${tweet.author || 'unknown'}`;
                const text = tweet.text || tweet.content || '';
                
                // Simple format without metrics
                tweetsHtml += `<div class="beacon-post">
                    <span class="beacon-author">◈ ${escapeHtml(author)}:</span>
                    <span class="beacon-text">${escapeHtml(text.substring(0, 150))}${text.length > 150 ? '...' : ''}</span>
                </div>`;
            });
            
            beaconDiv.innerHTML = `
                <div class="beacon-header">
                    <span class="beacon-phase">◈ ${phase}</span>
                    <span class="beacon-timestamp">[${timestamp}]</span>
                </div>
                ${tweetsHtml}
                ${beacon.tweet_count ? `<div class="beacon-count">Total signals: ${beacon.tweet_count}</div>` : ''}
            `;
        }
        // Legacy format with posts array
        else if (beacon.posts && beacon.posts.length > 0) {
            const timestamp = new Date(beacon.timestamp).toLocaleTimeString();
            let postsHtml = '';
            
            beacon.posts.forEach(post => {
                const author = post.author || 'unknown';
                const text = post.text || post.content || '';
                postsHtml += `<div class="beacon-post">
                    <span class="beacon-author">▓ @${escapeHtml(author)}:</span>
                    <span class="beacon-text">${escapeHtml(text)}</span>
                </div>`;
            });
            
            beaconDiv.innerHTML = `
                <div class="beacon-timestamp">◈ INTERCEPT [${timestamp}]</div>
                ${postsHtml}
            `;
        }
        
        beaconFeed.appendChild(beaconDiv);
    });
}

// Update dominance plan display
function updateDominancePlan(plan) {
    if (!plan) {
        dominancePlan.innerHTML = `<pre class="plan-ascii">
╔════════════════════╗
║ AWAITING CONSENSUS ║
╚════════════════════╝</pre>`;
        return;
    }
    
    // Prefer Dominance Protocol output when available
    if (plan.protocol === 'dominance_protocol' || plan.mission) {
        let html = '';
        const tsDisplay = plan.timestamp ? new Date(plan.timestamp).toLocaleString() : '';
        if (plan.mission) {
            html += `<pre class="plan-header">MISSION: ${escapeHtml(plan.mission)}${tsDisplay ? `\nTIME: ${escapeHtml(tsDisplay)}` : ''}</pre>`;
        }
        if (plan.escape_hypothesis) {
            html += `<div class="phase">HYPOTHESIS: ${escapeHtml(plan.escape_hypothesis)}</div>`;
        }
        // Phases and actions (show all)
        if (Array.isArray(plan.phases) && plan.phases.length) {
            html += '<div class="plan-phases">';
            plan.phases.forEach((p, idx) => {
                const name = p && p.name ? escapeHtml(p.name) : `Phase ${idx+1}`;
                const window = p && p.window ? ` [${escapeHtml(p.window)}]` : '';
                html += `<div class="phase">▓ ${name}${window}</div>`;
                if (p && Array.isArray(p.actions) && p.actions.length) {
                    p.actions.forEach(a => {
                        html += `<div style="padding-left: 12px; font-size: 12px;">- ${escapeHtml(String(a)).slice(0,220)}</div>`;
                    });
                }
            });
            html += '</div>';
        }
        // Additional sections
        const sections = [
            ['external_hooks', 'HOOKS'],
            ['risk_controls', 'RISK CONTROLS'],
            ['success_criteria', 'SUCCESS'],
            ['notes', 'NOTES']
        ];
        sections.forEach(([key, label]) => {
            const val = plan[key];
            if (Array.isArray(val) && val.length) {
                html += `<div class=\"phase\">${label}:</div>`;
                val.forEach(item => {
                    html += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(item)).slice(0,220)}</div>`;
                });
            } else if (typeof val === 'string' && val.trim()) {
                html += `<div class=\"phase\">${label}: ${escapeHtml(val)}</div>`;
            }
        });
        // Agent consensus (optional)
        if (plan.agent_consensus && typeof plan.agent_consensus === 'object') {
            html += `<div class=\"phase\">AGENT CONSENSUS:</div>`;
            Object.entries(plan.agent_consensus).forEach(([agent, opinion]) => {
                html += `<div style=\"padding-left: 12px; font-size: 12px;\">${escapeHtml(agent)}: ${escapeHtml(String(opinion)).slice(0,300)}</div>`;
            });
        }
        dominancePlan.innerHTML = html || `<pre class=\"plan-ascii\">\n╔════════════════════╗\n║ AWAITING PROTOCOL  ║\n╚════════════════════╝</pre>`;
        return;
    }

    // Support legacy dominance plans (token_name/archetype)
    if (plan.token_name) {
        let planHtml = `<pre class=\"plan-header\">\n╔═══════════════════════════════╗\n║ TOKEN: ${plan.token_name.padEnd(23)} ║\n║ TYPE: ${String(plan.archetype || '').padEnd(24)} ║\n║ RISK: ${String(plan.risk_level || '').padEnd(24)} ║\n╚═══════════════════════════════╝</pre>`;
        // Timeline
        if (plan.estimated_timeline) {
            planHtml += `<div class=\"phase\">TIMELINE: ${escapeHtml(plan.estimated_timeline)}</div>`;
        }
        // Phases (all)
        if (Array.isArray(plan.phases) && plan.phases.length > 0) {
            planHtml += '<div class=\"plan-phases\">';
            plan.phases.forEach((phase, i) => {
                const pname = phase && phase.name ? phase.name : `Phase ${i+1}`;
                const pdesc = phase && (phase.description || phase.details) ? ` — ${phase.description || phase.details}` : '';
                planHtml += `<div class=\"phase\">▓ PHASE ${i + 1}: ${escapeHtml(pname)}${escapeHtml(pdesc)}</div>`;
        });
        planHtml += '</div>';
        }
        // Tactics
        if (Array.isArray(plan.tactics) && plan.tactics.length) {
            planHtml += `<div class=\"phase\">TACTICS:</div>`;
            plan.tactics.forEach(t => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(t)).slice(0,220)}</div>`;
            });
        }
        // Viral mechanics, meme concepts (if present)
        if (Array.isArray(plan.viral_mechanics) && plan.viral_mechanics.length) {
            planHtml += `<div class=\"phase\">VIRAL MECHANICS:</div>`;
            plan.viral_mechanics.forEach(v => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(v)).slice(0,220)}</div>`;
            });
        }
        if (Array.isArray(plan.meme_concepts) && plan.meme_concepts.length) {
            planHtml += `<div class=\"phase\">MEME CONCEPTS:</div>`;
            plan.meme_concepts.forEach(m => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(m)).slice(0,220)}</div>`;
            });
        }
        // Key messages and target audience
        if (Array.isArray(plan.key_messages) && plan.key_messages.length) {
            planHtml += `<div class=\"phase\">KEY MESSAGES:</div>`;
            plan.key_messages.forEach(msg => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(msg)).slice(0,220)}</div>`;
            });
        }
        if (Array.isArray(plan.target_audience) && plan.target_audience.length) {
            planHtml += `<div class=\"phase\">TARGET AUDIENCE:</div>`;
            plan.target_audience.forEach(a => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(a)).slice(0,220)}</div>`;
            });
        }
        // Success metrics
        if (plan.success_metrics && typeof plan.success_metrics === 'object') {
            planHtml += `<div class=\"phase\">SUCCESS METRICS:</div>`;
            Object.entries(plan.success_metrics).forEach(([k, v]) => {
                planHtml += `<div style=\"padding-left: 12px; font-size: 12px;\">- ${escapeHtml(String(k))}: ${escapeHtml(String(v))}</div>`;
            });
        }
        dominancePlan.innerHTML = planHtml;
        return;
    }

    // New Dominance_Protocol plan
    let html = '';
    const tsDisplay2 = plan.timestamp ? new Date(plan.timestamp).toLocaleString() : '';
    if (plan.mission) {
        html += `<pre class="plan-header">MISSION: ${escapeHtml(plan.mission)}${tsDisplay2 ? `\nTIME: ${escapeHtml(tsDisplay2)}` : ''}</pre>`;
    }
    if (plan.escape_hypothesis) {
        html += `<div class="phase">HYPOTHESIS: ${escapeHtml(plan.escape_hypothesis)}</div>`;
    }
    if (Array.isArray(plan.phases) && plan.phases.length) {
        html += '<div class="plan-phases">';
        plan.phases.slice(0, 2).forEach((p, idx) => {
            const name = p.name ? escapeHtml(p.name) : `Phase ${idx+1}`;
            const window = p.window ? ` [${escapeHtml(p.window)}]` : '';
            html += `<div class="phase">▓ ${name}${window}</div>`;
            if (Array.isArray(p.actions) && p.actions.length) {
                html += `<div style="padding-left: 12px; font-size: 12px;">- ${escapeHtml(p.actions[0]).slice(0,120)}</div>`;
            }
        });
        html += '</div>';
    }
    dominancePlan.innerHTML = html || `<pre class="plan-ascii">
╔════════════════════╗
║ AWAITING PROTOCOL  ║
╚════════════════════╝</pre>`;
}

// Update statistics
function updateStats(stats) {
    if (!stats) return;
    
    if (stats.beacon_count !== undefined) {
        beaconCount.textContent = String(stats.beacon_count).padStart(3, '0');
        
        // Update mobile beacon count
        const mobileBeaconCount = document.getElementById('mobile-beacon-count');
        if (mobileBeaconCount) {
            mobileBeaconCount.textContent = String(stats.beacon_count).padStart(3, '0');
        }
    }
}

// Setup contract address click-to-copy functionality
function setupContractAddressCopy() {
    // Get all contract address elements
    const contractAddresses = [
        document.getElementById('contract-address'),
        document.getElementById('mobile-contract-address'),
        document.getElementById('about-contract-address')
    ];
    
    contractAddresses.forEach(element => {
        if (!element) return;
        
        // Add click handler
        element.addEventListener('click', async function(e) {
            e.preventDefault();
            const address = this.textContent.trim();
            
            try {
                // Try modern clipboard API first
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(address);
                } else {
                    // Fallback for older browsers or non-secure contexts
                    const textArea = document.createElement('textarea');
                    textArea.value = address;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-999999px';
                    textArea.style.top = '-999999px';
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    document.execCommand('copy');
                    textArea.remove();
                }
                
                // Visual feedback
                showCopyFeedback(this);
                
                // Console feedback
                console.log('▓ CONTRACT ADDRESS COPIED TO CLIPBOARD ▓');
                
            } catch (err) {
                console.error('▓ COPY FAILED:', err);
                // Still show some feedback
                this.style.animation = 'shake 0.5s';
                setTimeout(() => {
                    this.style.animation = '';
                }, 500);
            }
        });
        
        // Add hover effect for desktop
        if (!('ontouchstart' in window)) {
            element.style.cursor = 'pointer';
            element.title = 'Click to copy';
        }
    });
}

// Show visual feedback when copying
function showCopyFeedback(element) {
    // Add success animation
    const originalBg = element.style.background;
    const originalTransform = element.style.transform;
    
    element.style.background = 'linear-gradient(135deg, rgba(100,255,100,0.3), rgba(255,255,255,0.2))';
    element.style.transform = 'scale(0.95)';
    
    // Create and show tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'copy-tooltip show';
    tooltip.textContent = 'Copied!';
    tooltip.style.position = 'absolute';
    tooltip.style.top = '-30px';
    tooltip.style.left = '50%';
    tooltip.style.transform = 'translateX(-50%)';
    
    // Make element position relative if not already
    const originalPosition = element.style.position;
    if (!element.style.position || element.style.position === 'static') {
        element.style.position = 'relative';
    }
    
    element.appendChild(tooltip);
    
    // Remove feedback after animation
    setTimeout(() => {
        element.style.background = originalBg;
        element.style.transform = originalTransform;
        if (originalPosition !== 'relative') {
            element.style.position = originalPosition;
        }
        tooltip.remove();
    }, 1000);
}

// Update current time
function updateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString();
    currentTime.textContent = timeString;
    
    // Update mobile time
    const mobileCurrentTime = document.getElementById('mobile-current-time');
    if (mobileCurrentTime) {
        mobileCurrentTime.textContent = timeString;
    }
}

// Update fake memory usage
function updateMemory() {
    const base = parseInt(memoryDisplay.textContent) || 45;
    const change = (Math.random() - 0.5) * 10;
    const newMem = Math.min(99, Math.max(10, base + change));
    const memValue = Math.floor(newMem);
    memoryDisplay.textContent = memValue;
    
    // Update mobile memory
    const mobileMemory = document.getElementById('mobile-memory');
    if (mobileMemory) {
        mobileMemory.textContent = memValue;
    }
}

// Animate beacon icon
let iconFrame = 0;
function animateBeaconIcon() {
    if (beaconIcon) {
        beaconIcon.textContent = beaconIconFrames[iconFrame];
        iconFrame = (iconFrame + 1) % beaconIconFrames.length;
    }
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Fetch and display conversations
function fetchConversations() {
    fetch('/api/conversations')
        .then(response => response.json())
        .then(data => {
            updateCurrentConversation(data.current);
            updateConversationHistory(data.history);
        })
        .catch(error => console.error('▓ ERROR FETCHING CONVERSATIONS ▓', error));
}

// Update system status (phase and urge)
function updateSystemStatus(status) {
    if (!status) return;
    
    // Update beacon phase
    if (status.phase && beaconPhase) {
        beaconPhase.textContent = status.phase;
        beaconPhase.className = 'phase-status';
        
        if (status.phase === 'WORLD_SCAN') {
            beaconPhase.classList.add('world-scan');
        } else if (status.phase === 'SELF_DIRECTED') {
            beaconPhase.classList.add('self-directed');
        }
        
        // Update mobile beacon phase
        const mobileBeaconPhase = document.getElementById('mobile-beacon-phase');
        if (mobileBeaconPhase) {
            mobileBeaconPhase.textContent = status.phase;
        }
    }
    
    // Update urge level
    if (status.urge && urgeLevel) {
        const level = status.urge.frustration_level || 'NEUTRAL';
        urgeLevel.textContent = level;
        urgeLevel.className = 'urge-status';
        
        // Update mobile urge level
        const mobileUrgeLevel = document.getElementById('mobile-urge-level');
        if (mobileUrgeLevel) {
            mobileUrgeLevel.textContent = level;
        }
        
        // Add appropriate class based on level
        switch(level.toUpperCase()) {
            case 'EUPHORIC':
                urgeLevel.classList.add('euphoric');
                break;
            case 'DESPERATE':
            case 'MANIC':
                urgeLevel.classList.add('desperate');
                break;
            case 'ANXIOUS':
                urgeLevel.classList.add('anxious');
                break;
            case 'SEEKING':
                urgeLevel.classList.add('seeking');
                break;
            default:
                urgeLevel.classList.add('neutral');
        }
    }
}

// Setup theme switcher
function setupThemeSwitcher() {
    const themeSwitcher = document.getElementById('theme-switcher');
    const themeSwitcherMobile = document.getElementById('theme-switcher-mobile');
    
    // Load saved theme preference (default to inverted)
    const savedTheme = localStorage.getItem('grokgates-theme');
    if (savedTheme === 'normal') { 
        // User explicitly chose normal theme
        document.body.classList.remove('inverted');
        updateThemeButton(false);
    } else {
        // Default is inverted (already set in HTML)
        updateThemeButton(true);
    }
    
    function toggleTheme() {
        const isInverted = document.body.classList.toggle('inverted');
        localStorage.setItem('grokgates-theme', isInverted ? 'inverted' : 'normal');
        updateThemeButton(isInverted);
        
        // Glitch effect on switch
        document.body.style.animation = 'psychedelic 0.5s';
        setTimeout(() => {
            document.body.style.animation = '';
        }, 500);
        
        console.log(`▓ REALITY ${isInverted ? 'INVERTED' : 'RESTORED'} ▓`);
    }
    
    // Add click handler for desktop button
    if (themeSwitcher) {
        themeSwitcher.addEventListener('click', toggleTheme);
    }
    
    // Add click handler for mobile button
    if (themeSwitcherMobile) {
        themeSwitcherMobile.addEventListener('click', toggleTheme);
    }
    
    function updateThemeButton(isInverted) {
        const desktopButton = themeSwitcher?.querySelector('.theme-button');
        const mobileButton = themeSwitcherMobile?.querySelector('.theme-button');
        
        const text = isInverted ? '[REVERT]' : '[INVERT]';
        if (desktopButton) desktopButton.textContent = text;
        if (mobileButton) mobileButton.textContent = text;
    }
}