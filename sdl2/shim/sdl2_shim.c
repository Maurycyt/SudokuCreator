/*
 * wasm64 versions of the wrappers defined in src/shim.dk (keep the two in sync).
 *
 * duckc lowers `extern("C")` calls with the x86_64 SysV C ABI, also when its IR is retargeted
 * to wasm64, where by-value structs are passed through a hidden pointer (byval/sret). For the
 * wasm build, tools/duck_wasm.py compiles this file with emcc and drops the Duckling definitions
 * of the same symbols, so the by-value calls happen in C, compiled for the right target.
 * The native build does not use this file.
 */
#include <SDL.h>
#include <SDL_ttf.h>

SDL_Surface* dk_TTF_RenderUTF8_Blended(TTF_Font* font, const char* text, const SDL_Color* fg) {
	return TTF_RenderUTF8_Blended(font, text, *fg);
}

SDL_Surface* dk_TTF_RenderUTF8_Shaded(TTF_Font* font, const char* text, const SDL_Color* fg, const SDL_Color* bg) {
	return TTF_RenderUTF8_Shaded(font, text, *fg, *bg);
}

SDL_Surface* dk_TTF_RenderUTF8_Blended_Wrapped(TTF_Font* font, const char* text, const SDL_Color* fg, Uint32 wrap_length) {
	return TTF_RenderUTF8_Blended_Wrapped(font, text, *fg, wrap_length);
}

int dk_SDL_GUIDToString(const SDL_GUID* guid, char* buf, int size) {
	SDL_GUIDToString(*guid, buf, size);
	return 0;
}

int dk_SDL_GUIDFromString(const char* text, SDL_GUID* out) {
	*out = SDL_GUIDFromString(text);
	return 0;
}
