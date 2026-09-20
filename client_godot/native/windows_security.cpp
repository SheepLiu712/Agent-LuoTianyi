#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/packed_byte_array.hpp>
#include <windows.h>
#include <bcrypt.h>
#include <wincrypt.h>
#include <cstring>
#include <vector>
#include "pcm_stream_decoder.h"
#include "storage_volume.h"
using namespace godot;

namespace {
Dictionary result(const char *error, const PackedByteArray &data = PackedByteArray()) {
    Dictionary value;
    value["ok"] = error[0] == '\0';
    value["error"] = error;
    value["data"] = data;
    return value;
}
struct KeyHandle {
    BCRYPT_KEY_HANDLE value = nullptr;
    ~KeyHandle() { if (value) BCryptDestroyKey(value); }
};
struct LocalBuffer {
    DATA_BLOB value = {};
    ~LocalBuffer() {
        if (value.pbData) {
            SecureZeroMemory(value.pbData, value.cbData);
            LocalFree(value.pbData);
        }
    }
};
struct PasswordBytes {
    CharString value;
    explicit PasswordBytes(const String &password) : value(password.utf8()) {}
    ~PasswordBytes() { if (value.length()) SecureZeroMemory(value.ptrw(), value.length()); }
};

Dictionary dpapi(const PackedByteArray &input, const PackedByteArray &scope, bool decrypt) {
    if (input.is_empty() || input.size() > (decrypt ? 131072 : 65536) ||
            scope.is_empty() || scope.size() > 65536) return result("INVALID_INPUT");
    DATA_BLOB source{static_cast<DWORD>(input.size()), const_cast<BYTE *>(input.ptr())};
    DATA_BLOB entropy{static_cast<DWORD>(scope.size()), const_cast<BYTE *>(scope.ptr())};
    LocalBuffer output;
    const BOOL ok = decrypt
        ? CryptUnprotectData(&source, nullptr, &entropy, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &output.value)
        : CryptProtectData(&source, L"AgentLuo", &entropy, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &output.value);
    if (!ok) return result(decrypt ? "UNPROTECT_FAILED" : "PROTECT_FAILED");
    PackedByteArray bytes;
    bytes.resize(output.value.cbData);
    if (output.value.cbData) std::memcpy(bytes.ptrw(), output.value.pbData, output.value.cbData);
    return result("", bytes);
}
}

class WindowsSecurity : public RefCounted {
    GDCLASS(WindowsSecurity, RefCounted);
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("encrypt_password", "public_key_pem", "password"), &WindowsSecurity::encrypt_password);
        ClassDB::bind_method(D_METHOD("protect_secret", "plain", "scope"), &WindowsSecurity::protect_secret);
        ClassDB::bind_method(D_METHOD("unprotect_secret", "cipher", "scope"), &WindowsSecurity::unprotect_secret);
    }
public:
    Dictionary encrypt_password(const String &pem, const String &password) const {
        if (pem.is_empty() || pem.length() > 16384) return result("INVALID_KEY");
        const CharString encoded = pem.utf8();
        if (encoded.length() > 16384) return result("INVALID_KEY");
        DWORD size = 0;
        if (!CryptStringToBinaryA(encoded.get_data(), static_cast<DWORD>(encoded.length()),
                CRYPT_STRING_BASE64HEADER, nullptr, &size, nullptr, nullptr)) return result("INVALID_KEY");
        std::vector<BYTE> der(size);
        if (!CryptStringToBinaryA(encoded.get_data(), static_cast<DWORD>(encoded.length()),
                CRYPT_STRING_BASE64HEADER, der.data(), &size, nullptr, nullptr)) return result("INVALID_KEY");
        CERT_PUBLIC_KEY_INFO *info = nullptr;
        DWORD info_size = 0;
        if (!CryptDecodeObjectEx(X509_ASN_ENCODING, X509_PUBLIC_KEY_INFO, der.data(), size,
                CRYPT_DECODE_ALLOC_FLAG, nullptr, &info, &info_size)) return result("INVALID_KEY");
        KeyHandle key;
        const bool is_rsa = info->Algorithm.pszObjId && std::strcmp(info->Algorithm.pszObjId, szOID_RSA_RSA) == 0;
        const BOOL imported = is_rsa && CryptImportPublicKeyInfoEx2(X509_ASN_ENCODING, info, 0, nullptr, &key.value);
        LocalFree(info);
        if (!imported) return result("INVALID_KEY");
        DWORD bits = 0, copied = 0;
        if (BCryptGetProperty(key.value, BCRYPT_KEY_LENGTH, reinterpret_cast<PUCHAR>(&bits),
                sizeof(bits), &copied, 0) < 0 || bits < 2048 || bits > 8192) return result("INVALID_KEY");
        PasswordBytes plain(password);
        if (plain.value.length() > bits / 8 - 2 * 32 - 2) return result("INVALID_INPUT");
        BCRYPT_OAEP_PADDING_INFO padding{BCRYPT_SHA256_ALGORITHM, nullptr, 0};
        ULONG required = 0;
        auto *bytes = reinterpret_cast<PUCHAR>(plain.value.ptrw());
        const ULONG length = static_cast<ULONG>(plain.value.length());
        if (BCryptEncrypt(key.value, bytes, length, &padding, nullptr, 0, nullptr, 0,
                &required, BCRYPT_PAD_OAEP) < 0) return result("ENCRYPTION_FAILED");
        PackedByteArray cipher;
        cipher.resize(required);
        if (BCryptEncrypt(key.value, bytes, length, &padding, nullptr, 0, cipher.ptrw(), required,
                &required, BCRYPT_PAD_OAEP) < 0) return result("ENCRYPTION_FAILED");
        cipher.resize(required);
        return result("", cipher);
    }
    Dictionary protect_secret(const PackedByteArray &plain, const PackedByteArray &scope) const { return dpapi(plain, scope, false); }
    Dictionary unprotect_secret(const PackedByteArray &cipher, const PackedByteArray &scope) const { return dpapi(cipher, scope, true); }
};

void initialize_security(ModuleInitializationLevel level) {
    if (level == MODULE_INITIALIZATION_LEVEL_SCENE) {
        ClassDB::register_class<WindowsSecurity>();
        ClassDB::register_class<PcmStreamDecoder>();
        ClassDB::register_class<StorageVolume>();
    }
}
void terminate_security(ModuleInitializationLevel) {}
extern "C" GDExtensionBool GDE_EXPORT windows_security_init(
        GDExtensionInterfaceGetProcAddress address, GDExtensionClassLibraryPtr library,
        GDExtensionInitialization *initialization) {
    GDExtensionBinding::InitObject init(address, library, initialization);
    init.register_initializer(initialize_security);
    init.register_terminator(terminate_security);
    init.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_SCENE);
    return init.init();
}
