import XCTest
@testable import Minis

final class NanoMuseMcpOAuthTokensTests: XCTestCase {
    func testRequestNegotiatesJSONWithoutChangingFormBody() {
        let body = Data("grant_type=authorization_code&code=a%2Bb".utf8)
        let request = NanoMuseMcpOAuthTokens.request(endpoint: URL(string: "https://example.com/token")!, form: body)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "application/json")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/x-www-form-urlencoded")
        XCTAssertEqual(request.httpBody, body)
    }

    func testValidJSONTokens() throws {
        let tokens = try NanoMuseMcpOAuthTokens.parse(status: 200, data: Data(
            #"{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":3600}"#.utf8))
        XCTAssertEqual(tokens.accessToken, "fixture-access")
        XCTAssertEqual(tokens.refreshToken, "fixture-refresh")
        XCTAssertEqual(tokens.expiresIn, 3600)
    }

    func testHTTPOKErrorsTakePrecedenceAndDoNotExposeResponse() {
        assertFailure("incorrect_client_credentials", status: 200, body:
            #"{"error":"incorrect_client_credentials","error_description":"private response","access_token":"fixture-access"}"#)
        assertFailure("invalid_grant", status: 400, body: #"{"error":"invalid_grant"}"#)
        assertFailure("oauth_error", status: 200, body: #"{"error":"private response"}"#)
        assertFailure("oauth_error", status: 200, body: #"{"error":null,"access_token":"fixture-access"}"#)
    }

    func testNonJSONAndMalformedTokensAreRejected() {
        for body in ["error=incorrect_client_credentials&error_description=private", "<html>private</html>",
                     "[]", "{}", #"{"access_token":42}"#, #"{"access_token":"  "}"#] {
            assertFailure("invalid_token_response", status: 200, body: body)
        }
        assertFailure("HTTP 500", status: 500, body: "private response")
        assertFailure("HTTP 302", status: 302, body: #"{"access_token":"fixture-access"}"#)
    }

    private func assertFailure(_ code: String, status: Int, body: String,
                               file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertThrowsError(try NanoMuseMcpOAuthTokens.parse(status: status, data: Data(body.utf8)), file: file, line: line) {
            XCTAssertEqual(($0 as? NanoMuseMcpOAuthTokens.Failure)?.code, code, file: file, line: line)
        }
    }
}
