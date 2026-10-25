<script lang="ts">
  import { onMount } from 'svelte';
  import { Chess, SQUARES, type Square } from 'chess.js';
  import { Chessground } from 'chessground';
  import type { Api } from 'chessground/api';
  import type { Config } from 'chessground/config';
  import type { Key } from 'chessground/types';

  import 'chessground/assets/chessground.base.css';
  import 'chessground/assets/chessground.brown.css';
  import 'chessground/assets/chessground.cburnett.css';

  let {
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    interactive = true,
    orientation = 'white',
    viewMode = 'expanded',
    onmove
  }: {
    fen?: string;
    interactive?: boolean;
    orientation?: 'white' | 'black';
    viewMode?: 'expanded' | 'focused';
    onmove?: (move: { from: string; to: string; san: string }) => void;
  } = $props();

  let boardElement: HTMLDivElement | null = $state(null);
  let ground: Api | null = null;

  function refreshBounds() {
    if (ground) {
      try {
        // Clear cached bounds in chessground internal memo
        (ground as unknown as { state?: { dom?: { bounds?: { clear: () => void } } } }).state?.dom?.bounds?.clear();
        ground.redrawAll();
      } catch {
        // Fallback
      }
    }
  }

  function getLegalDests(c: Chess): Map<Key, Key[]> {
    const dests = new Map<Key, Key[]>();
    for (const sq of SQUARES) {
      const moves = c.moves({ square: sq, verbose: true });
      if (moves.length) {
        dests.set(sq as Key, moves.map((m) => m.to as Key));
      }
    }
    return dests;
  }

  function getConfig(): Config {
    const chess = new Chess(fen);
    return {
      fen,
      orientation,
      turnColor: chess.turn() === 'w' ? 'white' : 'black',
      movable: {
        free: false,
        color: interactive ? (viewMode === 'focused' ? orientation : 'both') : undefined,
        dests: interactive ? getLegalDests(chess) : new Map(),
        events: {
          after: (orig, dest) => {
            const currentChess = new Chess(fen);
            try {
              const move = currentChess.move({
                from: orig as Square,
                to: dest as Square,
                promotion: 'q'
              });
              if (move) {
                onmove?.({ from: move.from, to: move.to, san: move.san });
              }
            } catch {
              // Ignore illegal move attempts
            }
          }
        }
      },
      premovable: {
        enabled: false
      },
      highlight: {
        lastMove: true,
        check: true
      },
      animation: {
        enabled: true,
        duration: 200
      }
    };
  }

  onMount(() => {
    let ro: ResizeObserver | null = null;
    const clearBounds = () => {
      try {
        (ground as unknown as { state?: { dom?: { bounds?: { clear: () => void } } } })?.state?.dom?.bounds?.clear();
      } catch {
        // Fallback
      }
    };

    if (boardElement) {
      ground = Chessground(boardElement, getConfig());

      // Always clear cached bounds on interaction so clicks and drags evaluate fresh DOM coordinates
      boardElement.addEventListener('pointerdown', clearBounds, { capture: true });
      boardElement.addEventListener('mousedown', clearBounds, { capture: true });
      boardElement.addEventListener('touchstart', clearBounds, { capture: true });

      ro = new ResizeObserver(() => {
        refreshBounds();
      });
      ro.observe(boardElement);
    }

    return () => {
      if (boardElement) {
        boardElement.removeEventListener('pointerdown', clearBounds, { capture: true });
        boardElement.removeEventListener('mousedown', clearBounds, { capture: true });
        boardElement.removeEventListener('touchstart', clearBounds, { capture: true });
      }
      ro?.disconnect();
      ground?.destroy();
    };
  });

  // Re-synchronize chessground whenever fen, interactive, or orientation changes
  $effect(() => {
    if (ground) {
      ground.set(getConfig());
      refreshBounds();
    }
  });

  // Whenever viewMode changes, ensure fresh redraw and bounds re-computation
  $effect(() => {
    if (viewMode) {
      requestAnimationFrame(() => {
        refreshBounds();
        setTimeout(refreshBounds, 60);
        setTimeout(refreshBounds, 250);
      });
    }
  });
</script>

<div class="chessground_container">
  <div bind:this={boardElement} class="cg-wrap is2d brown cburnett"></div>
</div>

<style>
  .chessground_container {
    width: 100%;
    max-width: 580px;
    aspect-ratio: 1 / 1;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
    border-radius: 6px;
    overflow: hidden;
    user-select: none;
  }

  :global(.cg-wrap) {
    width: 100% !important;
    height: 100% !important;
    position: relative;
    display: block;
  }
</style>
