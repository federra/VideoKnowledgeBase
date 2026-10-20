import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {value() {this.open = true;}});
Object.defineProperty(HTMLDialogElement.prototype, 'close', {value() {this.open = false;}});
HTMLElement.prototype.scrollIntoView = vi.fn();
afterEach(cleanup);
