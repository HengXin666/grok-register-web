let socket = null;
// Multi-listener maps so app shell + page modules can subscribe without
// overwriting each other (Object.assign used to clobber page handlers).
const listeners = {
    onLog: new Set(),
    onLogReplay: new Set(),
    onStatusUpdate: new Set(),
    onRoundComplete: new Set(),
    onError: new Set(),
    onConnect: new Set(),
    onDisconnect: new Set(),
};

function addHandlers(h = {}) {
    for (const [key, fn] of Object.entries(h)) {
        if (typeof fn !== 'function' || !listeners[key]) continue;
        listeners[key].add(fn);
    }
}

function fanOut(key, data) {
    for (const fn of listeners[key]) {
        try {
            fn(data);
        } catch (err) {
            console.error(`socket handler ${key} failed`, err);
        }
    }
}

export function connectSocket(h = {}) {
    addHandlers(h);
    if (socket) return socket;
    socket = io({
        // Prefer websocket; fall back to polling. Auto-reconnect keeps the
        // dashboard ticking after brief network blips without a full refresh.
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 800,
        reconnectionDelayMax: 5000,
    });

    socket.on('log', (data) => fanOut('onLog', data));
    socket.on('log_replay', (data) => fanOut('onLogReplay', data));
    socket.on('status_update', (data) => fanOut('onStatusUpdate', data));
    socket.on('round_complete', (data) => fanOut('onRoundComplete', data));
    socket.on('error', (data) => fanOut('onError', data));

    socket.on('connect', () => {
        console.log('WebSocket connected');
        fanOut('onConnect');
    });

    socket.on('disconnect', (reason) => {
        console.log('WebSocket disconnected', reason);
        fanOut('onDisconnect', reason);
    });

    return socket;
}

/** Remove handlers previously registered via connectSocket (e.g. on page leave). */
export function disconnectSocketHandlers(h = {}) {
    for (const [key, fn] of Object.entries(h)) {
        if (typeof fn !== 'function' || !listeners[key]) continue;
        listeners[key].delete(fn);
    }
}

export function getSocket() {
    return socket;
}
