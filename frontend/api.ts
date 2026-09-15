import type { Hass, Request } from './types.ts';

export const REQUEST_TIMEOUT_MS = 15000;
/** A timeout releases the polling lock; late transport settlement has no consumer. */
export function request(hass: Hass, message: Request, timeout = REQUEST_TIMEOUT_MS): Promise<unknown> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`Request timed out: ${message.type}`)), timeout);
        Promise.resolve().then(() => hass.callWS(message)).then(
            result => { clearTimeout(timer); resolve(result); },
            error => { clearTimeout(timer); reject(error); },
        );
    });
}