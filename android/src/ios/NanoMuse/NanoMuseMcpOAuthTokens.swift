import Foundation

/// Negotiate JSON and expose only fixed error codes, never provider response text.
enum NanoMuseMcpOAuthTokens {
    struct Tokens {
        let accessToken: String
        let refreshToken: String?
        let expiresIn: Double
    }

    struct Failure: Error {
        let code: String
    }

    private static let errorCodes: Set<String> = [
        "invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
        "unsupported_grant_type", "invalid_scope", "access_denied", "server_error",
        "temporarily_unavailable", "incorrect_client_credentials", "redirect_uri_mismatch",
        "bad_verification_code", "unverified_user_email",
    ]

    static func request(endpoint: URL, form: Data) -> URLRequest {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = form
        return request
    }

    static func parse(status: Int, data: Data) throws -> Tokens {
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        if let json, json.keys.contains("error") {
            let code = json["error"] as? String
            throw Failure(code: code.flatMap { errorCodes.contains($0) ? $0 : nil } ?? "oauth_error")
        }
        guard (200...299).contains(status) else { throw Failure(code: "HTTP \(status)") }
        guard let json, let access = json["access_token"] as? String,
              !access.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw Failure(code: "invalid_token_response")
        }
        let refresh = (json["refresh_token"] as? String).flatMap {
            $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0
        }
        let expiry = (json["expires_in"] as? NSNumber)?.doubleValue ?? 0
        let expiresIn = expiry.isFinite && expiry > 0 && expiry <= Double(Int32.max) ? expiry : 0
        return Tokens(accessToken: access, refreshToken: refresh, expiresIn: expiresIn)
    }
}
